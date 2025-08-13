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
    # In a real app, you might want to handle this more gracefully
    exit()

# --- 3. CORE LOGIC ---
SUBJECT_TABLES = [
    'advance_engineering_mathematics_i', 'data_structures_and_algorithms',
    'data_structures_and_algorithms_lab', 'digital_electronics',
    'digital_electronics_lab', 'object_oriented_programming',
    'object_oriented_programming_lab', 'software_engineering',
    'software_engineering_lab', 'technical_communication'
]

def get_student_data(roll_no: str) -> dict:
    """Fetches all relevant data for a student."""
    print(f"Fetching data for Roll No: {roll_no}")
    try:
        # Get name and whatsapp_no from the new studentsrecord table
        student_info_res = supabase.table('studentsrecord').select('Name, whatsapp_no').eq('Roll_No', roll_no).single().execute()
        if not student_info_res.data:
            return {"error": "Student not found in studentsrecord."}
        
        student_details = student_info_res.data
        overall_present = 0
        overall_total = 0
        todays_attendance = []
        today_str = datetime.now().strftime('%d_%m_%Y')

        for table in SUBJECT_TABLES:
            try:
                # Fetch all columns, including today's date if it exists
                response = supabase.table(table).select(f'*, "{today_str}"').eq('Roll_No', roll_no).single().execute()
                if response.data:
                    for column, value in response.data.items():
                        if column.count('_') == 2 and value in ['P', 'A']:
                            overall_total += 1
                            if value == 'P': overall_present += 1
                    
                    if today_str in response.data and response.data[today_str] in ['P', 'A']:
                        todays_attendance.append({
                            "subject": table.replace('_', ' ').title(),
                            "status": response.data[today_str]
                        })
            except Exception:
                continue

        return {
            "name": student_details.get('Name'),
            "whatsapp_no": student_details.get('whatsapp_no'),
            "present": overall_present,
            "total": overall_total,
            "todays_attendance": todays_attendance
        }
    except Exception as e:
        print(f"Error fetching data for {roll_no}: {e}")
        return {"error": "An error occurred while fetching student data."}

def format_morning_message(data: dict) -> str:
    """Formats the predictive 7 AM message."""
    present, total = data['present'], data['total']
    if total == 0:
        return f"Hello {data['name']}! Welcome! Your attendance tracking starts today."

    current_perc = (present / total) * 100
    # Assuming 4 classes in a day for the prediction
    attend_all_perc = ((present + 4) / (total + 4)) * 100
    miss_all_perc = (present / (total + 4)) * 100

    message = f"☀️ Good Morning {data['name']}!\n\n"
    message += f"Your current overall attendance is *{current_perc:.2f}%* ({present}/{total}).\n\n"
    message += "*Today's Prediction (assuming 4 classes):*\n"
    message += f"✅ If you attend all classes: *{attend_all_perc:.2f}%*\n"
    message += f"❌ If you miss all classes: *{miss_all_perc:.2f}%*\n\n"
    message += "Have a great day at college!"
    return message

def format_evening_message(data: dict) -> str:
    """Formats the summary 4 PM message."""
    present, total = data['present'], data['total']
    current_perc = (present / total) * 100 if total > 0 else 0

    message = f"🌙 Good Evening {data['name']}!\n\n"
    message += f"Your updated overall attendance is *{current_perc:.2f}%* ({present}/{total}).\n\n"
    
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

# --- 4. WEB ROUTES & WEBHOOK HANDLER ---

@app.route('/')
def home():
    """A simple route to keep the service alive."""
    return "Attendance Notifier is running.", 200

@app.route('/new-student-webhook', methods=['POST'])
def handle_new_student():
    """Receives webhook from Supabase on new student registration."""
    payload = request.json
    print("Received new student webhook:", payload)
    
    if payload.get('type') == 'INSERT':
        record = payload.get('record', {})
        roll_no = record.get('Roll_No')
        if roll_no:
            print(f"New student registered: {roll_no}. Sending welcome message.")
            student_data = get_student_data(roll_no)
            if not student_data.get("error"):
                # Send the evening message as an instant summary
                message = format_evening_message(student_data)
                send_whatsapp_notification(student_data['whatsapp_no'], message)

    return {"status": "received"}, 200

# --- 5. SCHEDULER LOGIC ---

def run_scheduled_job(message_formatter):
    """Generic job to send notifications to all registered students."""
    print(f"\n--- Running Scheduled Job: {message_formatter.__name__} at {datetime.now()} ---")
    try:
        response = supabase.table('studentsrecord').select('Roll_No').execute()
        students = response.data
        print(f"Found {len(students)} students to notify.")
        for student in students:
            roll_no = student['Roll_No']
            student_data = get_student_data(roll_no)
            if not student_data.get("error"):
                message = message_formatter(student_data)
                send_whatsapp_notification(student_data['whatsapp_no'], message)
                time.sleep(1)
    except Exception as e:
        print(f"❌ Error during scheduled job: {e}")

def run_scheduler():
    """Continuously runs the scheduler in the background."""
    # Schedule jobs at specific times (in UTC, adjust for your server's timezone if needed)
    schedule.every().day.at("07:00").do(run_scheduled_job, format_morning_message)
    schedule.every().day.at("16:00").do(run_scheduled_job, format_evening_message)
    
    while True:
        schedule.run_pending()
        time.sleep(60) # Check every minute

# --- 6. START THE APP ---
if __name__ == "__main__":
    # Run the scheduler in a separate thread so it doesn't block the web server
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    # Run the Flask web app
    # The host and port are configured for Render
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
