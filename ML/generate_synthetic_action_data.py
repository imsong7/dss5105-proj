"""Generate synthetic emails for the required_action classifier.

The output is intentionally a separate file.  `train_email_ml.py` loads it
only for the training split, so every reported test score is still measured on
the original, human-labelled emails.

Run:
    python generate_synthetic_action_data.py
"""

from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = BASE_DIR / "synthetic_required_action.csv"
N_PER_CLASS = {
    "Needs a reply": 60,
    "Needs an action": 60,
    "Reminder": 60,
    "Further review": 20,
}
RANDOM_SEED = 20261023

LABELS = [
    "Needs a reply",
    "Needs an action",
    "Reminder",
    "Further review",
]

SLOTS = {
    "name": [
        "Amelia", "Wei Ming", "Priya", "Jun Hao", "Siti", "Daniel",
        "Mei Ling", "Arjun", "Grace", "Hafiz", "Chloe", "Rui En",
        "Nadia", "Kai Wen", "Shreya", "Marcus", "Aisyah", "Bryan",
    ],
    "sender": [
        "Dr Tan", "Prof Lim", "Ms Wong", "the Programme Office",
        "the Student Services Team", "the Course Administrator",
        "the Administrative Team", "the Module Coordinator",
        "the Student Affairs Office", "the Academic Office",
        "the Operations Team", "the Teaching Team",
        "the Department Office", "the Student Support Team",
    ],
    "course": [
        "DSS5101", "DSS5102", "DSS5103", "DSS5105", "DSS5201",
        "CS1010", "IS1108", "BT1101", "ACC1701", "EC1301",
        "MA1505", "ST2334",
    ],
    "date": [
        "12 November 2026", "18 November 2026", "25 November 2026",
        "3 December 2026", "9 December 2026", "15 December 2026",
        "7 January 2027", "14 January 2027", "21 January 2027",
    ],
    "date2": [
        "5 November 2026", "10 November 2026", "20 November 2026",
        "28 November 2026", "2 December 2026", "11 December 2026",
        "6 January 2027", "18 January 2027",
    ],
    "time": ["9:00 am", "10:30 am", "11:15 am", "2:00 pm", "3:30 pm", "4:00 pm"],
    "time2": ["12:00 noon", "5:00 pm", "6:00 pm", "8:00 pm"],
    "venue": [
        "LT27", "Seminar Room 3", "Block AS8 Level 4",
        "University Hall Auditorium", "Central Library Theatrette",
        "UHC Level 2", "the i3 Building", "COM3 Multi-purpose Room",
    ],
    "link": [
        "https://example.com/form/registration",
        "https://example.com/forms/student-update",
        "https://example.com/portal/submission",
        "https://example.com/survey/feedback",
        "https://example.com/booking/appointment",
    ],
    "email": [
        "student.services@example.com", "course.admin@example.com",
        "uhc.appointments@example.com", "career.services@example.com",
        "finance.help@example.com",
    ],
    "event": [
        "the DSS5105 industry panel", "the NUS career fair",
        "the UHC wellness talk", "the orientation briefing",
        "the research seminar", "the student leadership workshop",
        "the campus sustainability forum", "the alumni networking session",
        "the mid-autumn celebration", "the sustainability masterclass",
        "the career booster workshop", "the research showcase",
    ],
    "form": [
        "module preference form", "travel declaration form",
        "student update form", "course feedback form",
        "internship registration form", "safety declaration form",
    ],
    "document": [
        "medical certificate", "student declaration form", "updated CV",
        "academic transcript", "consent form", "proof of payment",
        "module registration form", "travel declaration", "safety waiver",
        "dataset", "data set", "questionnaire", "pre-visit questionnaire",
    ],
    "documents": [
        "supporting documents", "identity documents", "financial documents",
        "placement documents", "medical documents",
    ],
    "process": [
        "module registration", "hostel application", "graduation audit",
        "internship placement", "fee appeal", "exchange application",
    ],
    "item": [
        "student card", "lab equipment", "library book", "access card",
        "laptop loan", "safety goggles", "hostel key", "camera kit",
        "clinic visit invoice", "course materials fee", "lab fees",
        "hostel fees",
    ],
    "task": [
        "complete the module preference survey", "submit your travel claim",
        "update your emergency contact", "upload your internship report",
        "register for the safety briefing", "return the lab equipment",
        "complete the library survey", "renew your hostel agreement",
        "confirm your graduation details",
    ],
    "amount": ["$35", "$48.50", "$120", "$210", "$75", "$360"],
    "system": ["Canvas", "EduRec", "the student portal", "NUS email", "the library portal"],
    "office": [
        "the Registrar's Office", "the University Health Centre",
        "the Finance Office", "the Library", "Hostel Management",
    ],
    "facility": [
        "the swimming pool", "the central library", "the sports hall",
        "the computer lab", "the shuttle bus service",
    ],
    "location": [
        "the Kent Ridge campus", "Block AS8", "the UHC lobby",
        "the Central Library", "the sports centre",
    ],
    "topic": [
        "module registration", "academic integrity", "campus safety",
        "sustainable commuting", "student wellbeing", "research funding",
        "internship opportunities", "digital learning tools",
        "library collections", "exam preparation",
    ],
    "topic1": [
        "new research grants", "student awards", "curriculum updates",
        "campus events", "alumni stories", "sustainability initiatives",
    ],
    "topic2": [
        "upcoming seminars", "library workshops", "career talks",
        "community projects", "wellness programmes", "industry partnerships",
    ],
    "topic3": [
        "student support services", "new publications", "teaching innovations",
        "international exchanges", "volunteer opportunities",
    ],
    "speaker": [
        "Dr Nurul Hassan", "Prof Michael Chen", "Ms Kavitha Rao",
        "Dr Samuel Lee", "Assoc Prof Elaine Tan",
    ],
    "institution": [
        "the National University of Singapore", "Nanyang Technological University",
        "the Agency for Science, Technology and Research",
        "the Singapore Management University",
    ],
    "journal": [
        "the Journal of Applied Statistics", "Nature Sustainability",
        "the Singapore Economic Review", "Computers & Education",
    ],
    "organisation": [
        "the NUS Students' Union", "the Alumni Office",
        "the Sustainability Office", "the Community Engagement Team",
    ],
    "announcement": [
        "the campus shuttle schedule has changed",
        "the library has extended its opening hours",
        "a new student support centre has opened",
        "the exam timetable has been published",
        "the university has launched a new wellbeing programme",
    ],
    "newsletter": [
        "the NUS Research Digest", "the Campus Life Bulletin",
        "the Library Newsletter", "the Alumni Connect",
    ],
    "month": ["October", "November", "December", "January"],
    "policy": [
        "academic integrity policy", "data protection policy",
        "campus safety policy", "assessment and feedback policy",
    ],
    "programme": [
        "the undergraduate research programme", "the exchange programme",
        "the summer internship programme", "the peer mentoring programme",
    ],
    "role": [
        "student assistant", "research assistant", "peer mentor",
        "orientation leader", "lab demonstrator",
    ],
    "department": [
        "the Department of Statistics and Data Science", "the Library",
        "the Office of Student Affairs", "the Career Services Office",
    ],
    "person": ["Dr Aisha Rahman", "Mr Jonathan Koh", "Ms Priya Nair", "Dr Wei Zhang"],
    "activity": [
        "the campus clean-up", "the student welcome tea",
        "the coding workshop", "the wellness walk", "the alumni dinner",
    ],
    "group": ["the DSS5105 cohort", "the student committee", "the research team", "new students"],
    "option1": ["a morning session", "an online briefing", "a weekday slot", "Option A"],
    "option2": ["an afternoon session", "an on-campus briefing", "a weekend slot", "Option B"],
    "decision": ["the workshop timing", "the project topic", "the meeting format", "the field trip date"],
    "proposal": ["the revised module outline", "the new assessment plan", "the budget proposal", "the event plan"],
    "change": ["assessment weightings", "the project timeline", "the venue", "the reading list"],
    "material": ["the lecture slides", "the dataset", "the case study", "the survey template"],
    "context": ["the DSS5105 lecture", "the research seminar", "the student workshop", "the online course"],
    "booking": ["library room booking", "UHC appointment", "hostel room booking", "lab slot"],
    "details": [
        "12 November 2026 at 10:30 am", "18 November 2026 at 2:00 pm",
        "25 November 2026 at 9:00 am", "3 December 2026 at 3:30 pm",
    ],
    "order": ["the lab equipment order", "the catering order", "the printing order", "the furniture order"],
    "info": ["student ID", "application number", "booking reference", "matriculation number"],
    "assignment": [
        "DSS5105 project report", "DSS5101 problem set 3", "CS1010 practical",
        "IS1108 group presentation", "BT1101 lab report",
    ],
    "survey": [
        "module feedback survey", "student experience survey",
        "library services survey", "wellbeing survey",
        "pre-visit questionnaire", "module questionnaire",
        "student services questionnaire", "event feedback questionnaire",
    ],
    "purpose": ["course improvement", "service planning", "accreditation review", "programme evaluation"],
    "profile": ["student profile", "emergency contact details", "graduation record", "hostel profile"],
    "appointment": ["UHC appointment", "academic advising session", "career coaching session", "library consultation"],
    "briefing": ["safety briefing", "orientation briefing", "lab induction", "exchange briefing"],
    "training": ["research ethics training", "lab safety training", "data protection training", "teaching assistant training"],
    "duration": ["20 minutes", "45 minutes", "one hour", "90 minutes"],
    "claim": ["travel claim", "meal allowance claim", "conference expense claim", "taxi claim"],
    "account": ["NUS email account", "library account", "student portal account", "VPN account"],
    "software": ["the statistical software package", "the VPN client", "the plagiarism checker", "the data visualisation tool"],
    "membership": ["library membership", "sports membership", "alumni membership", "society membership"],
    "preference": ["project topic preference", "tutorial slot preference", "meal preference", "room preference"],
    "resource": ["tutorial slots", "lab benches", "hostel rooms", "project supervisors"],
    "requirement": ["the prerequisite module", "the English proficiency requirement", "the safety induction", "the internship requirement"],
    "field": ["module code", "contact number", "mailing address", "emergency contact"],
    "question": [
        "the deadline has been extended", "the submission format is flexible",
        "the workshop is open to all students", "the venue has changed",
    ],
}

TEMPLATES = {
    "Needs a reply": [
        (
            "Confirmation needed: {event} on {date}",
            "Dear {name},\n\nWe are finalising arrangements for {event} on {date}. Could you confirm whether you will be able to attend? Please reply by {date2} so that we can reserve your place.\n\nRegards,\n{sender}",
        ),
        (
            "Re: {course} group allocation",
            "Hi {name},\n\nI am putting together the group list for {course}. Are you available for a short meeting on {date} at {time}? Let me know which time works for you and I will send the meeting link.\n\nThanks,\n{sender}",
        ),
        (
            "Question about your {process}",
            "Dear {name},\n\nWe are reviewing your {process}. Could you clarify whether you have completed {requirement}? Please reply to this email with the details so that we can update your record.\n\nBest,\n{sender}",
        ),
        (
            "Availability for {role} interview",
            "Dear {name},\n\nWe would like to invite you for a short interview for the {role} position. Are you available on {date} at {time}? Kindly reply with your preferred slot.\n\nRegards,\n{sender}",
        ),
        (
            "Missing information for {process}",
            "Dear {name},\n\nYour {process} is incomplete because we still need {document}. Can you send it to us or confirm when you can provide it? Please respond by {date2}.\n\nThank you,\n{sender}",
        ),
        (
            "Can you review this before {date2}?",
            "Hi {name},\n\nI have attached the draft {document} for {course}. Could you take a look and let me know if the section on {topic} is accurate? I need your comments by {date2}.\n\nThanks,\n{sender}",
        ),
        (
            "RSVP: {event}",
            "Dear {name},\n\nYou are invited to {event} on {date} at {time}. Please let us know if you will attend and whether you have any dietary requirements. We need your reply by {date2}.\n\nBest,\n{sender}",
        ),
        (
            "Query on your {form} submission",
            "Hi {name},\n\nWe received your {form}, but the {field} field is blank. Could you confirm the correct value so that we can process it? Please reply at your earliest convenience.\n\nRegards,\n{sender}",
        ),
        (
            "Would you like to join {activity}?",
            "Hi {name},\n\nWe are organising {activity} for {group}. Would you like to join us? Please reply by {date2} so that we can reserve a place.\n\nCheers,\n{sender}",
        ),
        (
            "Feedback requested on {proposal}",
            "Dear {name},\n\nWe would appreciate your feedback on {proposal}. Do you support the proposed {change}? Kindly reply with your comments by {date2}.\n\nThank you,\n{sender}",
        ),
        (
            "Confirm your {booking} details",
            "Dear {name},\n\nPlease confirm that your {booking} details are correct: {details}. If anything needs to be changed, reply to this email by {date2}.\n\nBest,\n{sender}",
        ),
        (
            "Are you the right contact for {topic}?",
            "Hello,\n\nI was referred to you regarding {topic}. Could you confirm whether you are the right person to speak to? If not, could you point me to the correct contact?\n\nThanks,\n{sender}",
        ),
        (
            "Permission to use {material}",
            "Dear {name},\n\nMay I have your permission to use {material} in {context}? Please let me know if this is acceptable and whether you would like any changes.\n\nRegards,\n{sender}",
        ),
        (
            "Which {decision} do you prefer?",
            "Hi {name},\n\nWe have two options for {decision}: {option1} or {option2}. Which one would you prefer? Please reply by {date2} so that we can finalise the arrangements.\n\nThanks,\n{sender}",
        ),
        (
            "Follow-up: {topic}",
            "Dear {name},\n\nI am following up on my previous message about {topic}. Have you had a chance to consider it? I would appreciate your response by {date2}.\n\nBest,\n{sender}",
        ),
        (
            "Request for {document}",
            "Hi {name},\n\nCould you send me the latest version of {document}? I need it for {purpose}. Please reply with the file or let me know when it will be ready.\n\nThanks,\n{sender}",
        ),
        (
            "Invitation to speak at {event}",
            "Dear {name},\n\nWe would like to invite you to speak at {event} on {date}. Are you available and interested? Please reply by {date2} so that we can confirm the programme.\n\nRegards,\n{sender}",
        ),
        (
            "Student query about {course}",
            "Dear Professor,\n\nI am a student in {course}. I am unsure about {topic}. Could you clarify whether {question}? I would appreciate your guidance.\n\nThank you,\n{name}",
        ),
        (
            "Vendor confirmation for {order}",
            "Dear {name},\n\nWe are ready to process {order}. Can you confirm the delivery address and preferred date? Please reply by {date2}.\n\nRegards,\n{sender}",
        ),
        (
            "Checking in on {task}",
            "Hi {name},\n\nI wanted to check whether you have any updates on {task}. Could you let me know the current status? I need to update the team by {date2}.\n\nThanks,\n{sender}",
        ),
        (
            "Please confirm receipt of {document}",
            "Dear {name},\n\nCould you confirm that you have received the {document} we sent on {date}? Please reply by {date2} so that we can close the request.\n\nRegards,\n{sender}",
        ),
        (
            "Clarification needed on {topic}",
            "Dear {name},\n\nWe need clarification on {topic}. Could you explain how the requirements apply in this case? Please reply by {date2}.\n\nThank you,\n{sender}",
        ),
        (
            "Are you available to help with {activity}?",
            "Hi {name},\n\nWe are looking for volunteers for {activity} on {date}. Are you available to help? Please reply by {date2} so that we can finalise the list.\n\nThanks,\n{sender}",
        ),
    ],
    "Needs an action": [
        (
            "Action required: complete {form}",
            "Dear {name},\n\nPlease complete the {form} at {link} by {date}. You will need your {info} to submit it. Your application cannot be processed until the form is received.\n\nRegards,\n{sender}",
        ),
        (
            "Register for {event}",
            "Dear {name},\n\nRegistration for {event} is now open. Please register at {link} by {date}. Places are limited and will be allocated on a first-come basis.\n\nBest,\n{sender}",
        ),
        (
            "Submit your {assignment}",
            "Hi {name},\n\nYour {assignment} is due on {date} at {time}. Upload your file to {system} by the deadline. Please submit the file in PDF format.\n\nRegards,\n{sender}",
        ),
        (
            "Payment required for {item}",
            "Dear {name},\n\nPlease make payment of {amount} for {item} by {date}. You can pay through {link}. Your place will be confirmed after payment is received.\n\nRegards,\n{sender}",
        ),
        (
            "Complete the {survey}",
            "Dear {name},\n\nPlease complete the {survey} at {link} by {date}. Your feedback will be used for {purpose}. The survey takes about {duration}.\n\nThank you,\n{sender}",
        ),
        (
            "Upload supporting documents",
            "Dear {name},\n\nPlease upload your {documents} to {link} by {date}. We cannot process your {process} until the documents are received.\n\nRegards,\n{sender}",
        ),
        (
            "Sign and return {form}",
            "Dear {name},\n\nPlease sign the attached {form} and return it to {email} by {date}. You may use an electronic signature.\n\nBest,\n{sender}",
        ),
        (
            "Update your {profile}",
            "Dear {name},\n\nPlease update your {profile} at {link} by {date}. Make sure that your contact number and emergency contact are current.\n\nThank you,\n{sender}",
        ),
        (
            "Book your {appointment}",
            "Dear {name},\n\nPlease book your {appointment} at {link} before {date}. Slots are available from {date2} onwards. Bring your {item} to the appointment.\n\nRegards,\n{sender}",
        ),
        (
            "Attend the mandatory {briefing}",
            "Dear {name},\n\nYou are required to attend the {briefing} on {date} at {time} in {venue}. Please bring your {item} and arrive 10 minutes early.\n\nRegards,\n{sender}",
        ),
        (
            "Complete the {training} module",
            "Dear {name},\n\nPlease complete the {training} module at {link} by {date}. It takes about {duration}. A completion record will be added to your profile.\n\nRegards,\n{sender}",
        ),
        (
            "Submit your {claim}",
            "Dear {name},\n\nPlease submit your {claim} with receipts through {link} by {date}. Late submissions may not be processed.\n\nBest,\n{sender}",
        ),
        (
            "Activate your {account}",
            "Dear {name},\n\nPlease activate your {account} at {link} by {date}. You will need your {info} to complete the process.\n\nRegards,\n{sender}",
        ),
        (
            "Download and install {software}",
            "Dear {name},\n\nPlease download and install {software} from {link} before {date}. Contact {email} if you encounter any issues during installation.\n\nBest,\n{sender}",
        ),
        (
            "Prepare {material} for {event}",
            "Dear {name},\n\nPlease prepare {material} for {event} on {date}. Send the final version to {email} by {date2} so that it can be included in the programme.\n\nRegards,\n{sender}",
        ),
        (
            "Apply for {programme}",
            "Dear {name},\n\nApplications for {programme} close on {date}. Please apply through {link} and upload your {document}. Late applications will not be considered.\n\nBest,\n{sender}",
        ),
        (
            "Renew your {membership}",
            "Dear {name},\n\nYour {membership} expires on {date}. Please renew it at {link} to avoid any interruption to your access.\n\nRegards,\n{sender}",
        ),
        (
            "Submit your {preference}",
            "Dear {name},\n\nPlease submit your {preference} through {link} by {date}. This information will be used to allocate {resource}.\n\nThank you,\n{sender}",
        ),
        (
            "Complete the safety declaration",
            "Dear {name},\n\nPlease complete the safety declaration at {link} before attending {activity} on {date}. Entry will not be permitted without a completed declaration.\n\nRegards,\n{sender}",
        ),
        (
            "Return the borrowed {item}",
            "Dear {name},\n\nPlease return the borrowed {item} to {location} by {date}. A late fee applies after the due date.\n\nThank you,\n{sender}",
        ),
        (
            "Invoice for {item}",
            "Dear {name},\n\nPlease settle the attached invoice of {amount} for {item} by {date}. Payment can be made through {link}.\n\nRegards,\n{sender}",
        ),
        (
            "Submit your {document}",
            "Dear {name},\n\nPlease submit your {document} through {link} by {date}. We cannot process your {process} without it.\n\nRegards,\n{sender}",
        ),
        (
            "Verify your {profile}",
            "Dear {name},\n\nPlease verify your {profile} at {link} by {date}. Check that all details are accurate and update anything that has changed.\n\nThank you,\n{sender}",
        ),
    ],
    "Reminder": [
        (
            "Reminder: {form} due {date}",
            "Dear {name},\n\nThis is a reminder that the {form} is due on {date}. Please complete it at {link} if you have not done so.\n\nRegards,\n{sender}",
        ),
        (
            "Second reminder: {document}",
            "Dear {name},\n\nWe have not yet received your {document}. This is a second reminder to submit it by {date}. If you have already done so, please disregard this email.\n\nBest,\n{sender}",
        ),
        (
            "Final reminder: {event}",
            "Dear {name},\n\nThis is a final reminder to register for {event} by {date}. Registration will close at {time}.\n\nRegards,\n{sender}",
        ),
        (
            "Friendly reminder about {topic}",
            "Hi {name},\n\nJust a friendly reminder that the deadline for {topic} is approaching on {date}. Please make sure that you have completed the necessary steps.\n\nThanks,\n{sender}",
        ),
        (
            "Overdue: {item}",
            "Dear {name},\n\nOur records show that your {item} is now overdue. Please settle it by {date} to avoid any disruption to your access.\n\nRegards,\n{sender}",
        ),
        (
            "Don't forget: {task}",
            "Hi {name},\n\nDon't forget to {task} before {date}. Let us know if you need any help with the process.\n\nBest,\n{sender}",
        ),
        (
            "Reminder to submit {document}",
            "Dear {name},\n\nPlease be reminded to submit your {document} by {date}. We still have not received it.\n\nRegards,\n{sender}",
        ),
        (
            "Pending action: {task}",
            "Dear {name},\n\nYour {task} is still pending. Kindly complete it by {date}. If you believe this is an error, contact {email}.\n\nThank you,\n{sender}",
        ),
        (
            "Reminder: payment for {item}",
            "Dear {name},\n\nThis is a reminder that payment for {item} is due on {date}. Please pay through {link} to confirm your place.\n\nBest,\n{sender}",
        ),
        (
            "Reminder: {appointment} tomorrow",
            "Dear {name},\n\nThis is a reminder that your {appointment} is scheduled for {date} at {time}. Please arrive 10 minutes early and bring your {item}.\n\nRegards,\n{sender}",
        ),
        (
            "Last call for {document} submission",
            "Dear {name},\n\nThe deadline for {document} submission is {date}. This is a last call to submit your {document}. Late entries may not be accepted.\n\nBest,\n{sender}",
        ),
        (
            "Reminder: complete {training}",
            "Dear {name},\n\nYou have not yet completed the {training} module. Please complete it by {date}.\n\nRegards,\n{sender}",
        ),
        (
            "Outstanding {amount} for {item}",
            "Dear {name},\n\nOur records show an outstanding amount of {amount} for {item}. Please make payment by {date}. Contact {email} if you have already paid.\n\nThank you,\n{sender}",
        ),
        (
            "Reminder: return {item}",
            "Dear {name},\n\nThis is a reminder to return {item} by {date}. Please bring it to {location}.\n\nThank you,\n{sender}",
        ),
        (
            "Reminder: {event} starts {date}",
            "Dear {name},\n\nThis is a reminder that {event} starts on {date} at {time}. Please complete the pre-event checklist at {link}.\n\nBest,\n{sender}",
        ),
        (
            "Still pending: {task}",
            "Dear {name},\n\nWe are still waiting for your {task}. Please complete it as soon as possible, or by {date} at the latest.\n\nRegards,\n{sender}",
        ),
        (
            "Reminder: {document} still missing",
            "Dear {name},\n\nWe noticed that your {document} is still missing from our records. Please submit it by {date}.\n\nRegards,\n{sender}",
        ),
        (
            "Second notice: {topic}",
            "Dear {name},\n\nThis is a second notice regarding {topic}. Please take the necessary action by {date}.\n\nThank you,\n{sender}",
        ),
        (
            "Reminder: {form} not received",
            "Dear {name},\n\nWe have not received your completed {form}. Please submit it by {date} so that we can finalise your {process}.\n\nBest,\n{sender}",
        ),
        (
            "Reminder: {activity} on {date}",
            "Dear {name},\n\nThis is a reminder that {activity} will take place on {date} at {time}. Please remember to bring your {item}.\n\nRegards,\n{sender}",
        ),
        (
            "Reminder: {event} is tomorrow",
            "Dear {name},\n\nJust a reminder that {event} is tomorrow, {date}, at {time} in {venue}. We look forward to seeing you there.\n\nBest,\n{sender}",
        ),
        (
            "See you at {event} tomorrow",
            "Dear {name},\n\nWe look forward to seeing you at {event} tomorrow at {time}. Please arrive 10 minutes early.\n\nBest,\n{sender}",
        ),
        (
            "Reminder: payment for {item} is overdue",
            "Dear {name},\n\nOur records show that payment for {item} is overdue. Please pay {amount} by {date} to avoid any disruption.\n\nRegards,\n{sender}",
        ),
    ],
    "Further review": [
        (
            "FYI: {announcement}",
            "Dear {name},\n\nFor your information, {announcement}. No action is required. More details are available at {link}.\n\nRegards,\n{sender}",
        ),
        (
            "{newsletter} - {month} issue",
            "Dear {name},\n\nThe latest issue of {newsletter} is now available. It includes updates on {topic1}, {topic2}, and {topic3}. You can read it at {link}.\n\nBest,\n{sender}",
        ),
        (
            "Campus update: {topic}",
            "Dear {name},\n\nWe are writing to share an update on {topic}. The relevant information has been posted at {link}. This message is for your information only.\n\nRegards,\n{sender}",
        ),
        (
            "New policy: {policy}",
            "Dear {name},\n\nThe university has published the updated {policy}, effective {date}. The full document is available at {link}. You may review it at your convenience.\n\nRegards,\n{sender}",
        ),
        (
            "{event} recap",
            "Dear {name},\n\nThank you for being part of {event}. Photos and slides are now available at {link}. We hope you found the session useful.\n\nBest,\n{sender}",
        ),
        (
            "System maintenance notice",
            "Dear {name},\n\n{system} will undergo scheduled maintenance on {date} from {time} to {time2}. Services may be unavailable during this period.\n\nRegards,\n{sender}",
        ),
        (
            "Seminar announcement: {topic}",
            "Dear {name},\n\n{speaker} from {institution} will present a seminar on {topic} on {date} at {time} in {venue}. All are welcome.\n\nRegards,\n{sender}",
        ),
        (
            "Library resources update",
            "Dear {name},\n\nThe library has added new resources on {topic}. You can browse the collection at {link}. We hope you find them useful.\n\nBest,\n{sender}",
        ),
        (
            "Research update: {topic}",
            "Dear {name},\n\nOur research team has published a new report on {topic}. The report is available at {link}.\n\nBest regards,\n{sender}",
        ),
        (
            "Grade release notice",
            "Dear {name},\n\nResults for {course} are now available in {system}. You can view your grade at {link}.\n\nRegards,\n{sender}",
        ),
        (
            "Holiday closure notice",
            "Dear {name},\n\nPlease note that {office} will be closed on {date} for the public holiday. Normal operations will resume on {date2}.\n\nRegards,\n{sender}",
        ),
        (
            "New staff announcement",
            "Dear {name},\n\nWe are pleased to announce that {person} will join {department} as {role} from {date}. Please join us in welcoming them.\n\nBest,\n{sender}",
        ),
        (
            "News from {department}",
            "Dear {name},\n\nRead the latest news from {department}, including {topic1} and {topic2}. The full stories are available at {link}.\n\nRegards,\n{sender}",
        ),
        (
            "Event photos available",
            "Dear {name},\n\nThank you for being part of {event}. Photos from the day are now available at {link}. We hope you enjoy them.\n\nBest,\n{sender}",
        ),
        (
            "Updated opening hours",
            "Dear {name},\n\n{office} will operate on revised hours from {date}. The new hours are {time} to {time2} on weekdays.\n\nRegards,\n{sender}",
        ),
        (
            "Publication alert: {topic}",
            "Dear {name},\n\nA new article on {topic} has been published in {journal}. You can access it at {link}.\n\nBest,\n{sender}",
        ),
        (
            "Campus facilities notice",
            "Dear {name},\n\n{facility} will be unavailable on {date} due to scheduled works. Alternative arrangements are available at {location}.\n\nRegards,\n{sender}",
        ),
        (
            "Welcome to {programme}",
            "Dear {name},\n\nWelcome to {programme}. We have included some information about {topic} below. We look forward to seeing you on campus.\n\nBest,\n{sender}",
        ),
        (
            "IT service update",
            "Dear {name},\n\n{system} has been upgraded. You can now access the new features at {link}. No action is needed on your part.\n\nRegards,\n{sender}",
        ),
        (
            "Community announcement: {topic}",
            "Dear {name},\n\n{organisation} would like to share an update on {topic}. More details are available at {link}.\n\nBest,\n{sender}",
        ),
        (
            "Appointment confirmation: {appointment}",
            "Dear {name},\n\nThis email confirms your {appointment} on {date} at {time} in {venue}. No action is required. Please keep this message for your records.\n\nRegards,\n{sender}",
        ),
        (
            "Confirmation: {event} registration",
            "Dear {name},\n\nYour registration for {event} has been received. No further action is required. We look forward to seeing you on {date}.\n\nBest,\n{sender}",
        ),
        (
            "Your {booking} is confirmed",
            "Dear {name},\n\nYour {booking} has been confirmed for {date} at {time}. No action is required. Please keep this confirmation for your records.\n\nRegards,\n{sender}",
        ),
    ],
}

EXTRAS = {
    "Needs a reply": [
        "Your prompt response would be appreciated.",
        "Please let me know if you need any clarification.",
        "I am happy to discuss this further if that would help.",
    ],
    "Needs an action": [
        "Please keep a copy of your submission for your records.",
        "Contact us if you have any difficulty completing this step.",
        "Late submissions may not be accepted.",
    ],
    "Reminder": [
        "If you have already completed this, please disregard this message.",
        "Please contact us if you believe this notice was sent in error.",
        "Thank you for your prompt attention to this matter.",
    ],
    "Further review": [
        "No action is required.",
        "This message is for information only.",
        "We hope you find this update useful.",
    ],
}


def generate_rows(rng: random.Random) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    used: set[str] = set()
    counter = 0

    for label in LABELS:
        templates = list(TEMPLATES[label])
        first_pass = templates[:]
        rng.shuffle(first_pass)
        extras = EXTRAS[label]
        target = N_PER_CLASS[label]
        generated = 0
        attempts = 0
        while generated < target:
            attempts += 1
            if attempts > 20000:
                raise RuntimeError(f"Could not generate enough unique rows for {label}")
            if first_pass:
                subject_template, body_template = first_pass.pop()
            else:
                subject_template, body_template = rng.choice(templates)
            slots = {key: rng.choice(values) for key, values in SLOTS.items()}
            subject = subject_template.format(**slots)
            body = body_template.format(**slots)
            if rng.random() < 0.45:
                body = body.rstrip() + "\n\n" + rng.choice(extras)
            key = (subject + "\n" + body).strip().lower()
            if key in used:
                continue
            used.add(key)
            counter += 1
            generated += 1
            rows.append(
                {
                    "message_id": f"SYN-REQ-{counter:04d}",
                    "subject": subject,
                    "body": body,
                    "sender": slots["sender"],
                    "source_sheet": "synthetic_required_action",
                    "action": label,
                    "source": "synthetic",
                }
            )
    return rows


def main() -> None:
    rng = random.Random(RANDOM_SEED)
    rows = generate_rows(rng)
    frame = pd.DataFrame(rows)
    frame.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    print(f"Wrote {len(frame)} synthetic rows to {OUTPUT_FILE.name}")
    print("\nClass counts:")
    print(frame["action"].value_counts().to_string())
    print("\nSample:")
    print(frame[["subject", "action"]].head(8).to_string(index=False))


if __name__ == "__main__":
    main()
