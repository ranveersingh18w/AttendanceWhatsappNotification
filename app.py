import os
import time
from flask import Flask, request
from supabase import create_client, Client
from twilio.rest import Client as TwilioClient
from datetime import datetime
import schedule
import threading

# --- Flask App Initialization ---
app = Flask(__name__)

# --- 1. CREDENTIALS (Set these in Render's Environment Variables) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = 'whatsapp:+14155238886'

# --- 2. INITIALIZE CLIENTS ---
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    print("✅ Successfully connected to Supabase and Twilio.")
except Exception as e:
    print(f"❌ Error connecting to services: {e}")
    exit()

# --- 3. CORE LOGIC ---
SUBJECT_TABLES = [
    'advance_engineering_mathematics_i', 'data_structures_and_algorithms',
    'data_structures_and_algorithms_lab', 'digital_electronics',
    'digital_electronics_lab', 'object_oriented_programming',
    'object_oriented_programming_lab', 'software_engineering',
    'software_engineering_lab', 'technical_communication'
]

def format_subject_name(table_name):
    """Formats a table name into a readable subject name."""
    return table_name.replace('_', ' ').title()

def get_student_data(roll_no: str) -> dict:
    """
    Fetches all attendance data, separating theory and lab totals,
    mirroring the logic from the successful techno-njr app.
    """
    print(f"Fetching data for Roll No: {roll_no}")
    try:
        student_info_res = supabase.table('studentsrecord').select('Name, whatsapp_no').eq('Roll_No', roll_no).single().execute()
        if not student_info_res.data:
            return {"error": "Student not found in studentsrecord."}
        
        student_details = student_info_res.data
        theory_present, theory_total = 0, 0
        lab_present, lab_total = 0, 0
        todays_attendance = []
        today_str = datetime.now().strftime('%d_%m_%Y')

        for table in SUBJECT_TABLES:
            try:
                response = supabase.table(table).select(f'*').eq('Roll_No', roll_no).single().execute()
                if response.data:
                    subject_present, subject_total = 0, 0
                    for column, value in response.data.items():
                        if column.count('_') == 2 and value in ['P', 'A']:
                            subject_total += 1
                            if value == 'P':
                                subject_present += 1
                    
                    # Separate totals for theory and lab subjects
                    if table.endswith('_lab'):
                        lab_present += subject_present
                        lab_total += subject_total
                    else:
                        theory_present += subject_present
                        theory_total += subject_total

                    if today_str in response.data and response.data[today_str] in ['P', 'A']:
                        todays_attendance.append({
                            "subject": format_subject_name(table),
                            "status": response.data[today_str]
                        })
            except Exception:
                continue

        return {
            "name": student_details.get('Name'),
            "whatsapp_no": student_details.get('whatsapp_no'),
            "theory_present": theory_present, "theory_total": theory_total,
            "lab_present": lab_present, "lab_total": lab_total,
            "todays_attendance": todays_attendance
        }
    except Exception as e:
        print(f"❌ Critical error fetching data for {roll_no}: {e}")
        return {"error": "An error occurred while fetching student data."}

def format_morning_message(data: dict) -> str:
    """Formats the predictive 7 AM message using ONLY theory stats."""
    present, total = data['theory_present'], data['theory_total']
    if total == 0:
        return f"☀️ Good Morning {data['name']}! Your attendance tracking starts today."

    current_perc = (present / total) * 100
    attend_all_perc = ((present + 4) / (total + 4)) * 100
    miss_all_perc = (present / (total + 4)) * 100

    message = f"☀️ Good Morning {data['name']}!\n\n"
    message += f"Your current *Overall (Theory)* attendance is *{current_perc:.2f}%* ({present}/{total}).\n\n"
    message += "*Today's Prediction (assuming 4 theory classes):*\n"
    message += f"✅ Attend all classes: *{attend_all_perc:.2f}%*\n"
    message += f"❌ Miss all classes: *{miss_all_perc:.2f}%*\n\n"
    message += "Have a great day!"
    return message

def format_evening_message(data: dict) -> str:
    """Formats the summary 4 PM message using ONLY theory stats."""
    present, total = data['theory_present'], data['theory_total']
    current_perc = (present / total) * 100 if total > 0 else 0

    message = f"🌙 Good Evening {data['name']}!\n\n"
    message += f"Your updated *Overall (Theory)* attendance is *{current_perc:.2f}%* ({present}/{total}).\n\n"
    
    if data['todays_attendance']:
        message += "*Today's Summary:*\n"
        for item in data['todays_attendance']:
            status_emoji = "✅" if item['status'] == 'P' else "❌"
            message += f"  {status_emoji} {item['subject']}: {item['status']}\n"
    else:
        message += "No attendance was marked for you today.\n"
    return message

def send_whatsapp_notification(whatsapp_no: str, message: str):
    """Sends a message using Twilio."""
    if not whatsapp_no:
        print("Cannot send message, no WhatsApp number provided.")
        return
    try:
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message,
            to=f"whatsapp:{whatsapp_no}"
        )
        print(f"✅ Message sent to {whatsapp_no}")
    except Exception as e:
        print(f"❌ Failed to send message to {whatsapp_no}. Reason: {e}")

# --- 4. WEB ROUTES & WEBHOOKS ---

@app.route('/')
def home():
    """A simple route for UptimeRobot to keep the service alive."""
    return "Attendance Notifier is running and healthy.", 200

@app.route('/new-student-webhook', methods=['POST'])
def handle_new_student():
    """Receives webhook from Supabase on new student registration in 'studentsrecord'."""
    payload = request.json
    print("Received 'new-student-webhook':", payload)
    if payload.get('type') == 'INSERT':
        record = payload.get('record', {})
        roll_no = record.get('Roll_No')
        if roll_no:
            student_data = get_student_data(roll_no)
            if not student_data.get("error"):
                message = format_evening_message(student_data)
                send_whatsapp_notification(student_data.get('whatsapp_no'), message)
    return {"status": "received"}, 200

@app.route('/absent-alert-webhook', methods=['POST'])
def handle_absent_alert():
    """Receives webhook from Supabase when a student is marked absent."""
    payload = request.json
    print("Received 'absent-alert-webhook':", payload)
    if payload.get('type') == 'UPDATE':
        record = payload.get('record', {})
        old_record = payload.get('old_record', {})
        today_str = datetime.now().strftime('%d_%m_%Y')
        
        if record.get(today_str) == 'A' and old_record.get(today_str) != 'A':
            roll_no = record.get('Roll_No')
            table_name = payload.get('table')
            subject_name = format_subject_name(table_name)
            
            student_info_res = supabase.table('studentsrecord').select('whatsapp_no').eq('Roll_No', roll_no).single().execute()
            if student_info_res.data and student_info_res.data.get('whatsapp_no'):
                whatsapp_no = student_info_res.data['whatsapp_no']
                message = f"🚨 Absent Alert! You have been marked absent in today's *{subject_name}* class."
                send_whatsapp_notification(whatsapp_no, message)
    return {"status": "received"}, 200

# --- 5. SCHEDULER LOGIC ---

def run_scheduled_job(message_formatter):
    """Generic job to send notifications to all registered students."""
    job_name = message_formatter.__name__
    print(f"\n--- Running Scheduled Job: {job_name} at {datetime.now()} ---")
    try:
        response = supabase.table('studentsrecord').select('Roll_No').not_.is_('whatsapp_no', 'null').execute()
        students = response.data
        for student in students:
            roll_no = student['Roll_No']
            student_data = get_student_data(roll_no)
            if not student_data.get("error") and student_data.get("theory_total", 0) > 0:
                message = message_formatter(student_data)
                send_whatsapp_notification(student_data['whatsapp_no'], message)
                time.sleep(1)
    except Exception as e:
        print(f"❌ Error during scheduled job '{job_name}': {e}")

def run_scheduler():
    """Continuously runs the scheduler in the background."""
    schedule.every().day.at("07:00").do(run_scheduled_job, format_morning_message)
    schedule.every().day.at("16:00").do(run_scheduled_job, format_evening_message)
    while True:
        schedule.run_pending()
        time.sleep(60)

# --- 6. START THE APP ---
if __name__ == "__main__":
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
