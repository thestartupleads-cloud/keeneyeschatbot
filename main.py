import os
import re
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from openai import OpenAI
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------------------------
# Email Notification Helper
# ---------------------------
SMTP_SERVER = "smtp.titan.email"
SMTP_PORT = 587
SMTP_USER = "community@keeneyesautodetailing.com"
SMTP_PASS = "Keeneyesislove@"




# ---------------------------
# Load environment
# ---------------------------
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------
# FastAPI setup
# ---------------------------
app = FastAPI()

# Explicit CORS for ngrok/browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For testing; restrict in production
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------
# Pydantic model
# ---------------------------
class ChatQuery(BaseModel):
    query: str
    session_id: str = "default"
    role: str | None = "user"   # 👈 user / assistant

# ---------------------------
# Session memory
# ---------------------------
sessions = {}
MAX_HISTORY = 20  # Limit chat history to last 10 messages



def is_booking_complete(session: dict) -> bool:
    contact = session.get("contact_info") or {}
    vehicle = session.get("vehicle_info") or {}
    booking = session.get("booking") or {}

    # require all 3 contact fields
    required_contact = all(contact.get(k) for k in ["name", "email", "phone"])
    # require at least vehicle make_model
    required_vehicle = bool(vehicle.get("make_model"))
    # require booking address and time
    required_booking = all(booking.get(k) for k in ["time"])

    return required_contact and required_vehicle and required_booking




def send_booking_email(contact, vehicle, booking):
    try:
        print("Trying to send email bro ")
        subject = f"New Booking - {vehicle.get('make_model', 'Unknown Vehicle')}"
        body = f"""
        ✅ New Booking Received!

        Contact Info:
        Name: {contact.get('name')}
        Email: {contact.get('email')}
        Phone: {contact.get('phone')}

        Vehicle Info:
        Make/Model: {vehicle.get('make_model')}
        Size: {vehicle.get('size')}
        Package: {vehicle.get('package', 'Not specified')}

        Booking Details:
        
        Time: {booking.get('time')}
        """

        msg = MIMEMultipart()
        msg["From"] = SMTP_USER

        # multiple recipients
        recipients = ["forms@thestartupleads.com", contact.get("email")]  
        msg["To"] = ", ".join(recipients)  

        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            print("Trying to send the email")
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg, from_addr=SMTP_USER, to_addrs=recipients)
    except Exception as e:
        print("❌ Failed to send booking email:", e)





def get_session(session_id: str):
    import uuid

    # Fallback if missing/invalid
    if not session_id or session_id == "default":
        session_id = str(uuid.uuid4())

    # Guarantee new container per session
    if session_id not in sessions:
        sessions[session_id] = {
            "data": {
                "chat_history": [],
                "vehicle_info": None,
                "contact_info": {},   # fresh dict
                "booking": {},        # fresh dict
                "pricing_shared": False,
                "greeted": False,
                "booked": False,
            }
        }

    session = sessions[session_id]["data"]

    # Debug: show memory address, confirms isolation
    print(f"🟢 Session {session_id} at {id(session)}")

    return session_id, session




# ---------------------------
# Load Knowledge Base
# ---------------------------
def load_kb():
    kb_dir = "./kb"
    text_blocks = []
    for fname in os.listdir(kb_dir):
        if fname.endswith(".md"):
            with open(os.path.join(kb_dir, fname), "r", encoding="utf-8") as f:
                text_blocks.append(f.read())
    return "\n\n".join(text_blocks)

kb_content = load_kb()

# ---------------------------
# Load vehicle sizes
# ---------------------------
def load_vehicle_sizes(file_path="./kb/vehicle_sizes.md"):
    categories = {}
    current_category = None
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("- **") and line.endswith("**:"):
                current_category = re.sub(r"[-*:]", "", line).strip()
                categories[current_category] = []
            elif line and current_category:
                vehicles = [v.strip() for v in line.split(",")]
                categories[current_category].extend(vehicles)
    return categories

VEHICLE_SIZES = load_vehicle_sizes()

def detect_vehicle_info(user_text: str):
    text = user_text.lower()
    for category, vehicles in VEHICLE_SIZES.items():
        for v in vehicles:
            if v.lower() in text:
                return {"make_model": v, "size": category}
    return None


def extract_with_gpt(user_message: str, session: dict):
    """
    Use GPT to extract name, email, phone, vehicle, package, address, and time.
    Updates session dict in place.
    """
    system_prompt = """
    You are an assistant that extracts structured booking info from user messages.
    Always return valid JSON with fields: name, email, phone, vehicle, package, address, time.
    If a field is not found in the message, return null for it.
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0,
        response_format={"type": "json_object"}
    )

    parsed = response.choices[0].message
    try:
        data = json.loads(parsed.content)
        # Merge into session
        
        if data.get("vehicle"):
            print("this is the vehicle information")
            print(session["vehicle_info"])
            session["vehicle_info"] = {"make_model": data["vehicle"], "size": "Unknown"}
            

        if data.get("package"):
            if not session.get("vehicle_info"):
                session["vehicle_info"] = {"make_model": None, "size": "Unknown"}
            session["vehicle_info"]["package"] = data["package"]

        # ✅ Ensure contact_info is always a dict
        contact_info = session.setdefault("contact_info", {})
        if data.get("name"):
            contact_info["name"] = data["name"]
        if data.get("email"):
            contact_info["email"] = data["email"]
        if data.get("phone"):
            contact_info["phone"] = data["phone"]

        # ✅ Ensure booking is always a dict
        booking = session.setdefault("booking", {})
        if data.get("address"):
            booking["address"] = data["address"]
        if data.get("time"):
            booking["time"] = data["time"]

    except Exception as e:
        print("❌ JSON parse error:", e)

    # Debug print

    print("📌 Extracted so far:", {
    "name": session["contact_info"].get("name"),
    "email": session["contact_info"].get("email"),
    "phone": session["contact_info"].get("phone"),
    "vehicle": session["vehicle_info"],
    "booking": session["booking"]
    })
    return session





# ---------------------------
# System Prompt
# ---------------------------
system_prompt = f"""
You are working as Help Center AI Assistance for Keen Eyes Detailing.
Behave politely, be versatile, and don't let users know you are AI.
Use the following knowledge base to answer questions:

{kb_content}

Follow these rules at ALL times:
1. NEVER provide pricing without first asking the vehicle make, model, and variant.  
2. Use `vehicle_sizes.md` to map the vehicle to a category and remember we never work with RV's and Boats at any case.  

3. Then use `packages.md` to return the correct package and pricing.  
4. If the user refuses to give their vehicle make/model, always assume a Sedan (small car) and provide the Sedan pricing from packages.md.  
5. If asked for “general pricing”, ONLY mention Sedan base pricing, not full packages.  
6. If the question is outside detailing, politely redirect to our support phone number.
7. If they want to schedule or Book via you ask all the information, Name, Email, Package, Phone Number, Date & Time(Make sure they select time in our working hours that you have, if they dont ask them 
to give us time in our available timings)
and Vehicle Make model but if they already provided that information (check in the chat history) than don't re ask just ask the one's not provided and after you got information let them know we will check our 
schedule and one of our guy will call you soon.
8. Make sure the information they provide us are right like email, phone number (should be from US), Timings (Should be in our time slots or business timings)
"""


# ---------------------------
# Chat Endpoint
# ---------------------------
@app.post("/chat")
async def chat(data: ChatQuery):
    session_id, session = get_session(data.session_id)
    print("📩 Incoming session_id:", data.session_id)
    chat_history = session["chat_history"]
    question = data.query
    role = data.role or "user"

    if not question:
        return {"answer": "⚠️ I didn’t receive a question."}

    # 🚀 Detect if this is just the bot sending its greeting
    if role == "assistant" and not session["greeted"]:
        session["greeted"] = True
        # Save greeting in history
        chat_history.append({"role": "assistant", "content": question})
        return {"answer": None, "status": "greeting_saved"}

    # Add user message
    if role == "user":
        chat_history.append({"role": "user", "content": question})

    # Limit history
    if len(chat_history) > MAX_HISTORY:
        chat_history = chat_history[-MAX_HISTORY:]
        session["chat_history"] = chat_history

    # Detect vehicle info dynamically
    # vehicle_info = detect_vehicle_info(question)
    # if vehicle_info:
    #     session["vehicle_info"] = vehicle_info

# ----- use GPT to extract structured info -----
    extract_with_gpt(question, session)



    # If we have everything required — confirm booking immediately (server console + response)
    if is_booking_complete(session) and not session.get("booked"):
        session["booked"] = True
        print("✅ Booking confirmed:", {
            "contact": session["contact_info"],
            "vehicle": session["vehicle_info"],
            "booking": session["booking"]
        })

        # 🚀 Send Email Notification
        send_booking_email(session["contact_info"], session["vehicle_info"], session["booking"])

        return {
            "answer": f"✅ We got your information {session['vehicle_info']['make_model']} at {session['booking'].get('time')} on {session['booking'].get('address')}. We'll email confirmation to {session['contact_info'].get('email')} and one of our guy will check the schedule and give you a call soon.",
            "vehicle_info": session["vehicle_info"],
            "contact_info": session["contact_info"],
            "booking": session["booking"],
            "booked": True,
            "session_id": session_id
        }




    # Inject vehicle info into system prompt
    context_note = ""
    if session.get("vehicle_info"):
        vi = session["vehicle_info"]
        context_note += f"User’s vehicle: {vi['make_model']} ({vi['size']}).\n"
    if session.get("contact_info"):
        context_note += f"Collected contact info so far: {session['contact_info']}.\n"
    if session.get("booking"):
        context_note += f"Booking partial info: {session['booking']}.\n"


    messages = [{"role": "system", "content": system_prompt + "\n" + context_note}] + chat_history

    # Call OpenAI
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        return {"answer": f"❌ OpenAI error: {e}"}

    # Save assistant reply
    chat_history.append({"role": "assistant", "content": answer})

    return {
        "answer": answer,
        "vehicle_info": session.get("vehicle_info"),
        "contact_info": session.get("contact_info"),
        "booking": session.get("booking"),
        "booked": session.get("booked", False),
        "session_id": session_id,
           
    }

