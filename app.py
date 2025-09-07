from flask import Flask, render_template, request, send_file
from datetime import datetime, timedelta
from fpdf import FPDF
import tempfile

app = Flask(__name__)

# List of subjects
SUBJECTS = ["Math", "Physics", "Chemistry", "Biology", "English", "Hindi",
            "Accounts", "Economics", "Business Studies"]

def time_to_float(t):
    """Convert 'HH:MM' to float hours."""
    if not t:
        return 0.0
    parts = t.split(':')
    return int(parts[0]) + int(parts[1]) / 60.0

def generate_schedule(start_date_str, end_date_str,
                      school_start, school_end,
                      lunch_start, lunch_end,
                      dinner_start, dinner_end,
                      desired_hours, selected_subjects, progress_in):

    # Fallback defaults if None
    if not start_date_str:
        start_date_str = datetime.today().strftime("%Y-%m-%d")
    if not end_date_str:
        end_date_str = (datetime.today() + timedelta(days=7)).strftime("%Y-%m-%d")

    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    days = (end_date - start_date).days + 1

    # Convert times to float hours
    ss = time_to_float(school_start); se = time_to_float(school_end)
    ls = time_to_float(lunch_start); le = time_to_float(lunch_end)
    ds = time_to_float(dinner_start); de = time_to_float(dinner_end)

    # Free time slots
    free_template = []
    if ss > 0: free_template.append((0, ss))
    if se < ls: free_template.append((se, ls))
    if le < ds: free_template.append((le, ds))
    if de < 24: free_template.append((de, 24))

    selected = selected_subjects[:]
    progress = {s: float(progress_in.get(s, 0.0)) for s in selected}
    remaining = {s: max(0.0, 100.0 - progress[s]) for s in selected}

    progress_rate_per_hour = 2.0
    schedule_by_date = {}

    for d_offset in range(days):
        day = start_date + timedelta(days=d_offset)
        free_times = free_template[:]
        total_free = sum((end - start) for start, end in free_times)
        study_hours = min(desired_hours, total_free)

        if study_hours <= 0 or not selected:
            schedule_by_date[str(day)] = ["No study hours available or no subjects selected."]
            continue

        # Weight by remaining work
        eps = 1e-6
        weights = {s: remaining[s] + eps for s in selected}
        total_w = sum(weights.values())
        if total_w <= 0:
            weights = {s: 1.0 for s in selected}
            total_w = len(selected)

        alloc = {s: (weights[s] / total_w) * study_hours for s in selected}

        # Rotate subjects for variety
        rot = d_offset % len(selected)
        order = selected[rot:] + selected[:rot]

        day_lines = []
        used_hours_per_subject = {s: 0.0 for s in selected}

        for block_start, block_end in free_times:
            block_remaining = block_end - block_start
            cursor = block_start
            for s in order:
                want = alloc.get(s, 0.0)
                if want <= 0: continue
                take = min(want, block_remaining)
                if take <= 0: continue
                sub_start = cursor
                sub_end = cursor + take
                sh = int(sub_start); sm = int((sub_start - sh) * 60)
                eh = int(sub_end); em = int((sub_end - eh) * 60)
                line = f"{s}: {sh:02d}:{sm:02d} - {eh:02d}:{em:02d} ({take:.2f} hrs)"
                day_lines.append(line)
                cursor = sub_end
                block_remaining = block_end - cursor
                alloc[s] -= take
                used_hours_per_subject[s] += take
                if block_remaining <= 1e-6: break

        # Update progress
        for s in selected:
            gain = used_hours_per_subject[s] * progress_rate_per_hour
            progress[s] = min(100.0, progress[s] + gain)
            remaining[s] = max(0.0, 100.0 - progress[s])

        snapshot = [f"{s}: {progress[s]:.1f}%" for s in selected]
        day_lines.append("")
        day_lines.append("Progress after this day:")
        day_lines.extend(snapshot)
        schedule_by_date[str(day)] = day_lines

    final_progress = {s: progress[s] for s in selected}
    return schedule_by_date, final_progress

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", subjects=SUBJECTS, datetime=datetime, timedelta=timedelta)

@app.route("/generate", methods=["POST"])
def generate():
    form = request.form

    # ✅ Use fallback defaults to prevent errors
    current_date = form.get("current_date") or datetime.today().strftime("%Y-%m-%d")
    exam_date = form.get("exam_date") or (datetime.today() + timedelta(days=7)).strftime("%Y-%m-%d")

    schedule, final_progress = generate_schedule(
        current_date,
        exam_date,
        form.get("school_start"),
        form.get("school_end"),
        form.get("lunch_start"),
        form.get("lunch_end"),
        form.get("dinner_start"),
        form.get("dinner_end"),
        float(form.get("desired_hours") or 0.0),
        form.getlist("subjects"),
        {s: float(form.get(f"progress_{s}", 0)) for s in SUBJECTS}
    )
    return render_template("schedule.html", schedule=schedule, final_progress=final_progress, request=request)

@app.route("/download_pdf", methods=["POST"])
def download_pdf():
    form = request.form

    # Same default handling
    current_date = form.get("current_date") or datetime.today().strftime("%Y-%m-%d")
    exam_date = form.get("exam_date") or (datetime.today() + timedelta(days=7)).strftime("%Y-%m-%d")

    schedule, final_progress = generate_schedule(
        current_date,
        exam_date,
        form.get("school_start"),
        form.get("school_end"),
        form.get("lunch_start"),
        form.get("lunch_end"),
        form.get("dinner_start"),
        form.get("dinner_end"),
        float(form.get("desired_hours") or 0.0),
        form.getlist("subjects"),
        {s: float(form.get(f"progress_{s}", 0)) for s in SUBJECTS}
    )

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    for day, lines in schedule.items():
        pdf.add_page()
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, f"WebWizard Plan for {day}", ln=True, align="C")
        pdf.set_font("Arial", "", 11)
        for ln in lines:
            pdf.multi_cell(0, 8, ln)

    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmpname = tf.name
    tf.close()
    pdf.output(tmpname)
    return send_file(tmpname, as_attachment=True, download_name="WebWizard_plan.pdf")

if __name__ == "__main__":
    app.run(debug=True)
