#!/usr/bin/env python
"""Write bert/synthetic.csv: hand-written synthetic emails for a NUS student inbox.

Focus: the weak action labels (needs_reply, needs_action, reminder) plus hard negatives
(no_immediate_action mails that mention dates, links or the word "reply").
Every row is marked is_synthetic=1 / label_source=synthetic. train_full.py only ever puts
these rows into the TRAIN split, so validation/test stay real emails.

    python bert/make_synthetic.py     # -> bert/synthetic.csv
"""
import csv
import hashlib
import os
import random

random.seed(5105)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "synthetic.csv")

# (subject, sender, body, category, action)
E = []
def add(subject, sender, body, category, action):
    E.append((subject, sender, body.strip(), category, action))

# --------------------------------------------------------------------------- #
# needs_reply: a person asks a question / expects a written answer
# --------------------------------------------------------------------------- #
add("Availability for project consultation next week", "Tan Wei Ling <weiling.tan@nus.edu.sg>",
    "Hi all, I would like to meet each project group for a short 20-minute consultation next week. Could you reply with two time slots that work for your group between Tuesday and Thursday afternoon? Best, Wei Ling", "general", "needs_reply")
add("Re: DSS5105 group 7 - who is taking the EDA section?", "Daniel Koh <e1234567@u.nus.edu>",
    "Hey, just following up on yesterday's call. Can you let me know by tonight whether you are fine taking the EDA part? If not I can swap with you and do the modelling instead. Thanks!", "general", "needs_reply")
add("quick q about the lab report", "jiahui <e0987321@u.nus.edu>",
    "hiii sorry to bother, did u manage to get the regression output for part 3? mine keeps giving NaN for the coefficients. what did u do for the missing values?", "general", "needs_reply")
add("Your interest in the Data Analyst Intern role", "Priya Raman <priya.raman@gsk-talent.com>",
    "Dear Candidate, thank you for applying for the Data Analyst Intern position. We would like to arrange a 30-minute phone screen. Could you please reply with your availability over the next five working days and the best number to reach you?", "career", "needs_reply")
add("Teaching assistant position - are you still interested?", "Prof. Lim Chee Keong <stalimck@nus.edu.sg>",
    "Dear Student, you indicated interest in tutoring DSA1101 last semester. We have one opening for Semester 2. Please let me know by Friday whether you are still interested, and which tutorial slots you could take.", "career", "needs_reply")
add("Housemate wanted - still looking?", "Marcus <marcus.yeo88@gmail.com>",
    "Hi, I saw your post in the PG housing group. Are you still looking for a room near Kent Ridge? The room is available from 1 December, $1,150 including utilities. Let me know if you want to view it this weekend.", "others", "needs_reply")
add("Feedback on your draft proposal", "Dr. Aisha Rahman <aisha.r@nus.edu.sg>",
    "Hi, I have read your draft. Overall the motivation is clear, but I am not sure which dataset you plan to use for the carbon intensity baseline. Can you clarify this in a short reply before I sign off on the proposal?", "general", "needs_reply")
add("Can you share the slides from today?", "Kevin Ong <e1122334@u.nus.edu>",
    "Hi! I missed the last 15 minutes of the seminar because of a clash. Would you be able to send me the slides or your notes? Thanks a lot.", "general", "needs_reply")
add("Dinner on Friday?", "Hana Kim <hana.kim.sg@gmail.com>",
    "Hey!! A few of us from the orientation group are planning dinner at Clementi on Friday 7pm. Are you coming? Need to tell the restaurant the headcount by Thursday.", "others", "needs_reply")
add("Re: Re: Data request for capstone", "Liang Hao <liang.hao@sustainalytics-partner.com>",
    "Thanks for your note. Before we can share the emissions dataset, could you tell me which fields you need and whether the results will be published? A short description of the project would also help.", "career", "needs_reply")
add("Question about your Kaggle notebook", "Arjun Mehta <arjun.mehta.ds@outlook.com>",
    "Hi, I came across your notebook on PM2.5 forecasting and really liked the feature engineering. Did you tune the LightGBM parameters manually or with Optuna? Would you be open to a short chat about it?", "others", "needs_reply")
add("Interview confirmation - please reply", "Talent Acquisition <careers@shopee-recruit.com>",
    "Hello, we have tentatively scheduled your technical interview on 14 November at 3:00pm SGT. Kindly reply to this email to confirm the timing, or propose an alternative if it does not suit you.", "career", "needs_reply")
add("Mentorship programme - intro call", "Rachel Chua <rachel.chua@alumni.nus.edu.sg>",
    "Hi there, I have been matched as your alumni mentor. I would love to set up a 30-min intro call. What days usually work for you, and do you prefer Zoom or meeting in person on campus?", "career", "needs_reply")
add("Re: absence from tutorial", "Tutor DSS5101 <dss5101.tutor@nus.edu.sg>",
    "Thanks for letting me know. Could you tell me which week's tutorial you will be missing so I can arrange a make-up slot? Also please confirm if you will submit the worksheet online.", "general", "needs_reply")
add("Which topic did your group pick?", "Coordinator DSS5105 <dss5105@nus.edu.sg>",
    "Dear groups, a few of you have not told us your project topic yet. Please reply to this email with your group number and chosen topic so we can assign mentors.", "general", "needs_reply")
add("Clinic follow-up: how are you feeling?", "University Health Centre <uhc_followup@nus.edu.sg>",
    "Dear patient, you visited UHC last week for a persistent cough. Could you reply to let us know whether your symptoms have improved? If not, we will arrange a review with the doctor.", "medical", "needs_reply")
add("Counselling session - preferred time?", "Student Wellness <wellness_appt@nus.edu.sg>",
    "Hi, thank you for reaching out to Student Wellness. Our counsellor has openings on Wednesday at 10am and Thursday at 4pm. Please reply with the slot you prefer and whether you would like it online or in person.", "medical", "needs_reply")
add("Re: volunteering at the open house", "NUS Statistics Society <statsoc@u.nus.edu>",
    "Hi! Thanks for signing up. We still need helpers for the morning booth. Could you reply and let us know if you can do 9am to 12pm on Saturday?", "others", "needs_reply")
add("Your opinion on the survey questions", "Mei Ling <e0876543@u.nus.edu>",
    "Hey, I've drafted the user survey for our project (attached). Could you have a look and tell me whether question 4 and 7 are too leading? Want to finalise it tomorrow.", "general", "needs_reply")
add("Hello from your exchange buddy", "Lukas Becker <lukas.becker@tum.de>",
    "Hi! I'm Lukas, your buddy from TUM for the joint workshop. When are you arriving in Munich, and do you need help finding accommodation? Looking forward to hearing from you.", "others", "needs_reply")
add("Recommendation letter - details needed", "Prof. Wong Siew Mei <stawsm@nus.edu.sg>",
    "Dear student, I am happy to write the recommendation. Please reply with the list of programmes, their deadlines, and a short summary of the projects you did in my course so I can be specific.", "career", "needs_reply")
add("Re: GPU access for the course project", "Research Computing <hpc-help@nus.edu.sg>",
    "Hello, to process your request we need a bit more information. How many GPU hours do you expect to need, and which framework will you be using? Please reply to this ticket.", "general", "needs_reply")
add("你下周有空吗？", "王小明 <xiaoming.wang@u.nus.edu>",
    "嗨！我们几个同学想周三下午一起准备期中考试，你要不要一起来？请回复我一下，我好订图书馆的讨论室。", "general", "needs_reply")
add("Want to study together?", "Park Ji-min <jimin.park@u.nus.edu>",
    "Hi! I'm Park Ji-min from the stats class. Want to study together every Thursday evening? Please let me know.", "general", "needs_reply")
add("Freelance analysis work?", "Sam Lee <sam@greenmetrics.io>",
    "Hi, a friend recommended you. We are a small sustainability start-up and need help analysing energy usage data for about 10 hours a week. Would you be interested? Happy to share more details if you reply.", "career", "needs_reply")
add("Re: research assistant application", "Dr. Benjamin Tay <btay@nus.edu.sg>",
    "Thank you for your interest. Before we proceed, could you tell me how many hours per week you can commit this semester, and whether you have experience with spatial data in Python?", "career", "needs_reply")
add("Lost water bottle?", "Security Lobby S16 <s16_lobby@nus.edu.sg>",
    "Hello, a blue water bottle with your matric sticker was handed in at the S16 lobby. Could you reply to confirm it is yours and let us know when you can collect it?", "others", "needs_reply")
add("Re: the shared drive", "Nur Aisyah <e0765432@u.nus.edu>",
    "I moved the cleaned files into /final but I'm not sure if you wanted the raw ones deleted. Should I keep both versions? Tell me before I clean up tonight.", "general", "needs_reply")

# --------------------------------------------------------------------------- #
# needs_action: do something other than replying (form, pay, upload, register, verify)
# --------------------------------------------------------------------------- #
add("[Action Required] Update your emergency contact by 15 Nov", "Registrar's Office <regbox@nus.edu.sg>",
    "Dear Students, our records show that your emergency contact information is incomplete. Please log in to the Student Portal and update it by 15 November 2026. Failure to do so may delay your semester registration.", "general", "needs_action")
add("Submit your timesheet for October", "Department Admin <stats_admin@nus.edu.sg>",
    "Dear Student Assistants, please submit your October timesheet through the HR portal by 3 November. Late submissions will be paid in the next cycle.", "career", "needs_action")
add("Complete your pre-departure health declaration", "Global Relations Office <gro_exchange@nus.edu.sg>",
    "Dear outgoing exchange student, please complete the health declaration form at the link below before your flight. You will not be able to collect your travel insurance card until the form is submitted.", "medical", "needs_action")
add("Verify your email to activate your account", "DataCamp <no-reply@datacamp.com>",
    "Welcome! Please click the button below to verify your email address and activate your free student account. This link expires in 24 hours.", "others", "needs_action")
add("Your library fine is overdue", "NUS Libraries <libfines@nus.edu.sg>",
    "Dear user, you have an outstanding fine of S$4.50 for an overdue item. Please make payment via the library portal. Borrowing privileges are suspended until the fine is cleared.", "general", "needs_action")
add("Sign your internship offer letter", "HR Onboarding <onboarding@dbs-careers.com>",
    "Congratulations! Your internship offer is ready. Please review and e-sign the offer letter in the candidate portal by 20 November. Once signed, we will send your onboarding checklist.", "career", "needs_action")
add("Register for the graduate writing workshop (limited seats)", "Centre for English Language <celc_pg@nus.edu.sg>",
    "Dear postgraduate students, registration for the thesis writing workshop is now open. Seats are limited to 30. Please register via the form below if you wish to attend.", "general", "needs_action")
add("Upload your vaccination record", "University Health Centre <uhc_records@nus.edu.sg>",
    "Dear student, as part of hall admission, please upload a copy of your vaccination record to the health portal before 30 November. Admission cannot be confirmed without it.", "medical", "needs_action")
add("Book your graduation photo slot", "Commencement Office <commencement@nus.edu.sg>",
    "Dear graduand, photo slots for the December ceremony are now open. Please choose your slot through the booking link. Unbooked graduands will be assigned a slot automatically.", "general", "needs_action")
add("Complete the mandatory lab safety quiz", "Faculty of Science Safety <fos_safety@nus.edu.sg>",
    "All students using the wet labs must complete the online safety quiz on Canvas Quizzes before 10 November. Lab access cards will be deactivated for those who have not passed.", "general", "needs_action")
add("Confirm your attendance via the RSVP form", "Graduate Students' Society <gss_events@u.nus.edu>",
    "Hi everyone! The end-of-semester mixer is on 28 November. Please fill in the RSVP form so we can order food. Only those who RSVP will receive a ticket.", "others", "needs_action")
add("Your claim needs additional documents", "Student Insurance Desk <insurance@nus.edu.sg>",
    "Dear student, your medical claim submitted on 12 October is incomplete. Please upload the original receipt and the doctor's memo through the claims portal within 14 days.", "medical", "needs_action")
add("Pay your hostel fee for Semester 2", "Office of Housing Services <ohs_fees@nus.edu.sg>",
    "Dear resident, the hostel fee for Semester 2 is now available in your account. Please make payment by 5 January 2027 via GIRO or PayNow to keep your room allocation.", "general", "needs_action")
add("Action needed: set up two-factor authentication", "NUS IT Care <itcare@nus.edu.sg>",
    "Dear user, to protect your account please set up multi-factor authentication by 1 December. After this date you will not be able to log in to NUS systems without it.", "others", "needs_action")
add("Accept your module allocation", "ModReg <modreg@nus.edu.sg>",
    "You have been allocated DSA5208 for Semester 2. Please log in to EduRec and accept the allocation by Round 2 closing, otherwise the seat will be released.", "general", "needs_action")
add("Complete your onboarding tasks", "Grab Early Talent <earlytalent@grab-careers.com>",
    "Hi! Before your first day, please complete the background check form and upload a copy of your student pass in Workday. Both items must be done before 1 December.", "career", "needs_action")
add("Please fill in the module feedback survey", "Student Feedback <sfeedback@nus.edu.sg>",
    "Dear students, the feedback exercise is mandatory and closes on 22 November. Please complete the survey for each module you are taking; grades will be released only after completion.", "general", "needs_action")
add("Reset your password - it expires in 3 days", "NUS IT Care <itcare@nus.edu.sg>",
    "Your NUSNET password will expire in 3 days. Please change it via the self-service portal to avoid losing access to email and Wi-Fi.", "others", "needs_action")
add("Submit your CV for the career fair resume book", "Centre for Future-ready Graduates <cfg_postgrad@nus.edu.sg>",
    "Employers attending Career Fest will receive a resume book. If you would like to be included, upload your CV in PDF to the TalentConnect portal by 10 November.", "career", "needs_action")
add("Your appointment needs to be confirmed online", "Polyclinic Appointments <appointments@nhgp.com.sg>",
    "Dear patient, your dental appointment on 19 November is pending. Please confirm or reschedule through the HealthHub app within 48 hours, otherwise the slot will be released.", "medical", "needs_action")
add("（必填）活动报名表", "新加坡中国学生学者联合会 <cssa_events@u.nus.edu>",
    "各位同学好！本周六的中秋晚会需要提前报名，请大家在周四晚上之前填写报名表，链接如下。没有报名的同学可能无法入场。", "others", "needs_action")
add("[Required] Student union fee payment", "NUS Korean Student Association <kosa.nus@gmail.com>",
    "Hello, this is NUS Korean Student Association. The fee payment deadline for this semester is November 15. Please transfer to the account below and be sure to write your name in the Google form.", "others", "needs_action")
add("Download and sign the NDA before the hackathon", "Hackathon Team <hello@greenhack.sg>",
    "Thanks for registering for GreenHack 2026! Before you can access the datasets, please download the NDA, sign it, and upload it to the participant portal.", "career", "needs_action")
add("Collect your matriculation card", "Student Service Centre <ssc@nus.edu.sg>",
    "Your student card is ready. Please collect it in person at the Student Service Centre with your passport between 9am and 5pm on weekdays.", "general", "needs_action")

# --------------------------------------------------------------------------- #
# reminder: a date/time is given, but no specific action or reply is requested
# --------------------------------------------------------------------------- #
add("Reminder: DSS5102 lecture moved to LT27 this Friday", "DSS Programme Office <dss_admin@nus.edu.sg>",
    "Dear students, a gentle reminder that this Friday's lecture (14 November) will take place in LT27 instead of the usual venue. The timing remains 6:30pm to 9:30pm.", "general", "reminder")
add("See you tomorrow at the Data Science Seminar", "DSDS Events <stabox1@nus.edu.sg>",
    "Dear registered participants, this is a reminder that the seminar on causal inference starts tomorrow at 2pm in S16-06-118. Light refreshments will be served after the talk.", "general", "reminder")
add("Your appointment is tomorrow at 10:30am", "University Health Centre <uhc_appt@nus.edu.sg>",
    "This is a reminder of your appointment with Dr Lee tomorrow, 12 November, at 10:30am at UHC Level 2. Please arrive 10 minutes early.", "medical", "reminder")
add("Library closure on Deepavali", "NUS Libraries <libinfo@nus.edu.sg>",
    "Please note that all NUS libraries will be closed on 8 November for the Deepavali public holiday. Regular opening hours resume on 9 November.", "general", "reminder")
add("Planned system maintenance this Saturday", "NUS IT Care <itcare@nus.edu.sg>",
    "Email and Canvas services will be unavailable on Saturday, 15 November, from 2am to 6am due to scheduled maintenance. We apologise for any inconvenience.", "general", "reminder")
add("Exam timetable released", "Registrar's Office <regbox@nus.edu.sg>",
    "The final examination timetable for Semester 1 is now available on EduRec. Examinations will be held from 22 November to 6 December 2026.", "general", "reminder")
add("Reminder: Career Fest is next Wednesday", "Centre for Future-ready Graduates <cfg_postgrad@nus.edu.sg>",
    "A quick reminder that NUS Career Fest takes place next Wednesday, 19 November, from 11am to 5pm at the MPSH. Over 80 employers will be present.", "career", "reminder")
add("Your session starts in 1 hour", "Zoom Events <no-reply@zoom.us>",
    "Your registered session \"Mock Interview Clinic\" starts today at 4:00pm SGT. You can join using the link in your registration email.", "career", "reminder")
add("Flu vaccination clinic this Thursday", "University Health Centre <uhc_info@nus.edu.sg>",
    "UHC will be running a walk-in flu vaccination clinic this Thursday, 13 November, from 9am to 1pm at the UHC atrium.", "medical", "reminder")
add("Reminder: Teambuilding Day on 21 November", "DSS Programme Office <dss_admin@nus.edu.sg>",
    "Dear students, this is a friendly reminder that the Teambuilding Day will be held on 21 November starting 9am at Sentosa. Transport will depart from UTown at 8:15am.", "general", "reminder")
add("Shuttle bus schedule during recess week", "Transport Office <transport@nus.edu.sg>",
    "Please note that internal shuttle services will run on a reduced schedule during recess week (24 to 28 November). Normal service resumes on 1 December.", "general", "reminder")
add("Project presentation week - schedule", "Coordinator DSS5105 <dss5105@nus.edu.sg>",
    "Dear all, final project presentations will take place in Week 13 on Tuesday and Thursday evenings. Your group's slot is listed in the table below.", "general", "reminder")
add("Your physiotherapy session on Monday", "Sports Medicine Centre <smc_appt@nus.edu.sg>",
    "This is to remind you of your physiotherapy session on Monday, 17 November, at 3pm. The session will last about 45 minutes.", "medical", "reminder")
add("Reminder: Pre-departure briefing on 2 December", "Global Relations Office <gro_exchange@nus.edu.sg>",
    "A reminder that the pre-departure briefing for outgoing exchange students will be held on 2 December at 2pm in the Shaw Foundation Alumni House auditorium.", "general", "reminder")
add("Mid-term break: no tutorials next week", "Tutor DSS5101 <dss5101.tutor@nus.edu.sg>",
    "Hi all, just a note that there will be no tutorials next week because of the mid-term break. Tutorials resume on 3 November with Worksheet 6.", "general", "reminder")
add("Webinar tomorrow: Careers in ESG Analytics", "Sustainable Finance Institute <events@sfi-asia.org>",
    "Thank you for registering. The webinar \"Careers in ESG Analytics\" will begin tomorrow at 12:30pm SGT and run for one hour.", "career", "reminder")
add("Office hours cancelled this Wednesday", "Dr. Aisha Rahman <aisha.r@nus.edu.sg>",
    "Dear students, my office hours this Wednesday (12 Nov) are cancelled as I will be at a conference. They will resume as usual the following week.", "general", "reminder")
add("Reminder: last day of classes is 14 November", "Registrar's Office <regbox@nus.edu.sg>",
    "This is a reminder that the last day of instruction for Semester 1 is Friday, 14 November 2026. Reading week follows from 15 to 21 November.", "general", "reminder")
add("明天的讲座提醒", "新加坡中国学生学者联合会 <cssa_events@u.nus.edu>",
    "提醒一下：明天晚上7点在UTown有职业分享讲座，已报名的同学请准时到场。", "career", "reminder")
add("Regular meeting tomorrow", "NUS Korean Student Association <kosa.nus@gmail.com>",
    "- External Email - Regular meeting tomorrow at 7pm at UTown Seminar Room 3. Please note.", "others", "reminder")
add("Blood donation drive on campus next week", "NUS Red Cross Youth <rcy@u.nus.edu>",
    "The Health Sciences Authority mobile donation bus will be at the Central Library forecourt next Tuesday and Wednesday from 10am to 4pm.", "medical", "reminder")

# --------------------------------------------------------------------------- #
# hard negatives: no_immediate_action (dates, links or "reply" words, but nothing to do)
# --------------------------------------------------------------------------- #
add("Your submission has been received", "Gradescope <no-reply@gradescope.com>",
    "This email confirms that your submission for Assignment 3 was received on 10 November at 11:42pm. No further action is required.", "general", "no_immediate_action")
add("Receipt for your payment", "NUS Student Finance <ofnbox3@nus.edu.sg>",
    "Thank you. We have received your payment of S$4,150.00 for Semester 1 tuition fees on 30 September 2026. This receipt is for your records.", "general", "no_immediate_action")
add("This week in sustainability: November newsletter", "GreenBiz Weekly <newsletter@greenbiz-weekly.com>",
    "In this issue: new carbon border rules in the EU, a profile of Singapore's green bond market, and five upcoming ESG events. Read online or forward to a friend.", "promotional", "no_immediate_action")
add("50% off annual plan - ends Sunday", "Notion <team@makenotion.com>",
    "Students get 50% off the Plus plan this week only. Offer ends Sunday 23:59. Upgrade anytime from your workspace settings.", "promotional", "no_immediate_action")
add("Your order has shipped", "Lazada <noreply@lazada.sg>",
    "Good news! Your order #SG2611039 has been shipped and is expected to arrive between 13 and 15 November.", "promotional", "no_immediate_action")
add("Please do not reply: password changed successfully", "NUS IT Care <itcare@nus.edu.sg>",
    "Your NUSNET password was changed on 9 November at 10:15pm. If you made this change, you can ignore this email. This mailbox is not monitored; please do not reply.", "others", "no_immediate_action")
add("Recap: what we covered at the Career Talk", "Centre for Future-ready Graduates <cfg_postgrad@nus.edu.sg>",
    "Thank you to everyone who attended last week's career talk. The slides and recording are now available on the CFG website for your reference.", "career", "no_immediate_action")
add("Department news: new faculty members", "DSDS Communications <stabox1@nus.edu.sg>",
    "We are pleased to welcome three new faculty members to the Department of Statistics and Data Science this semester. Read about their research interests below.", "general", "no_immediate_action")
add("Your appointment has been completed", "University Health Centre <uhc_appt@nus.edu.sg>",
    "Thank you for visiting UHC today. Your consultation summary is available in the patient portal. Wishing you a speedy recovery.", "medical", "no_immediate_action")
add("Jobs you may be interested in", "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
    "15 new jobs match your preferences: Data Analyst at Grab, Junior Data Scientist at Singtel, ESG Analyst at UOB and more.", "career", "no_immediate_action")
add("Thanks for your feedback!", "Student Feedback <sfeedback@nus.edu.sg>",
    "We have recorded your feedback for DSS5101. Your responses are anonymous and will help improve the module. Thank you for taking part.", "general", "no_immediate_action")
add("Weekend deals at the Co-op", "NUS Co-op <coop_promo@nus.edu.sg>",
    "Stationery bundles from $5, 20% off hoodies and free tote bag with every purchase above $30. Valid this weekend only at the UTown outlet.", "promotional", "no_immediate_action")
add("Re: thanks!", "Kevin Ong <e1122334@u.nus.edu>",
    "Got the slides, thank you so much! See you in class next week.", "general", "no_immediate_action")
add("Registration confirmed: Resume Clinic", "Centre for Future-ready Graduates <cfg_postgrad@nus.edu.sg>",
    "You are registered for the Resume Clinic. Your registration number is RC-2611-084. We look forward to seeing you.", "career", "no_immediate_action")
add("Monthly health tips: sleep and exam stress", "Student Wellness <wellness@nus.edu.sg>",
    "Exam season is around the corner. Here are five evidence-based tips to sleep better and manage stress, plus a list of free campus resources.", "medical", "no_immediate_action")
add("Your Spotify Premium Student renewed", "Spotify <no-reply@spotify.com>",
    "Your Premium Student plan was renewed on 8 November for S$5.49. You can view your receipts in your account page.", "promotional", "no_immediate_action")
add("Year in review: GSS 2026", "Graduate Students' Society <gss_events@u.nus.edu>",
    "What a year! Over 40 events, 2,000 participants, and a new mentoring scheme. Thank you for being part of the community.", "others", "no_immediate_action")
add("Scholarship disbursement processed", "NUS Student Finance <ofnbox3@nus.edu.sg>",
    "Your scholarship stipend for November has been credited to your bank account on 5 November 2026.", "general", "no_immediate_action")

# --------------------------------------------------------------------------- #
# realistic wrappers (lengths/boilerplate vary like the real Outlook export)
# --------------------------------------------------------------------------- #
INTERNAL = ("nus.edu.sg", "u.nus.edu")
SIGNATURES = [
    "", "", "",
    "\n\nBest regards,\n{name}",
    "\n\nThanks,\n{name}",
    "\n\nRegards,\n{name}\nDepartment of Statistics and Data Science\nNational University of Singapore",
]
FOOTERS = [
    "", "", "", "",
    "\n\nImportant: This email is confidential and may be privileged. If you are not the intended recipient, please delete it and notify us immediately; you should not copy or use it for any purpose, nor disclose its contents to any other person. Thank you.",
    "\n\nYou are receiving this email because you are a registered student of NUS.",
]


def wrap(sender, body):
    name = sender.split("<")[0].strip() or "Team"
    domain = sender.split("@")[-1].rstrip(">").lower()
    text = body + random.choice(SIGNATURES).format(name=name)
    if not domain.endswith(INTERNAL):
        text = "- External Email - " + text
    return text + random.choice(FOOTERS)


def main():
    rows = []
    for subj, sender, body, cat, act in E:
        prev = wrap(sender, body)
        rid = "syn_" + hashlib.sha1((subj + sender + prev).encode()).hexdigest()[:8]
        rows.append({"review_id": rid, "Subject": subj, "From": sender, "Preview": prev,
                     "category": cat, "action": act, "label_source": "synthetic", "is_synthetic": "1"})
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print(f"wrote {len(rows)} rows -> {OUT}")
    print("action  :", dict(Counter(r["action"] for r in rows)))
    print("category:", dict(Counter(r["category"] for r in rows)))


if __name__ == "__main__":
    main()
