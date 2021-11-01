from datetime import datetime
import os
import sys
import json

import requests
from flask import Flask, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS, cross_origin

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://nffthvokcyobhu:f4c0d9da0d068825a65a9f624bbde7c86c09901858d41666782ebc4ea2a9cd2c@ec2-34-196-34-142.compute-1.amazonaws.com:5432/d84ffm5uq4bh7e'
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = 'secret string'
db = SQLAlchemy(app)
cors = CORS(app)
app.config['CORS_HEADERS'] = 'Content-Type'


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.String(80), nullable=False)
    recipient_id = db.Column(db.String(80), nullable=False)
    message = db.Column(db.String(), nullable=False)
    time = db.Column(db.DateTime, nullable=False)

    def __init__(self, sender_id, recipient_id, time, message):
        self.sender_id = sender_id
        self.recipient_id = recipient_id
        self.time = time
        self.message = message


class FbUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(80), unique=True, nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    last_name = db.Column(db.String(80), nullable=False)
    profile_pic = db.Column(db.String(), nullable=False)

    def __init__(self, user_id, first_name, last_name, profile_pic):
        self.user_id = user_id
        self.first_name = first_name
        self.last_name = last_name
        self.profile_pic = profile_pic


class FbPage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.String(80), unique=True, nullable=False)
    page_name = db.Column(db.String(80), nullable=False)
    questions = db.relationship('Question', backref='fb_page', lazy=False)

    def __init__(self, page_id, page_name,):
        self.page_id = page_id
        self.page_name = page_name


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(), nullable=False)
    page_id = db.Column(db.String, db.ForeignKey('fb_page.page_id'),
                        nullable=False)
    answers = db.relationship(
        'Answer', backref='question', cascade="all, delete-orphan",
        lazy=False, foreign_keys='Answer.question_id')
    previous_answer_id = db.Column(
        db.Integer, db.ForeignKey('answer.id', ondelete="cascade"), nullable=True)

    def __init__(self, question, page_id, previous_answer_id):
        self.question = question
        self.page_id = page_id
        self.previous_answer_id = previous_answer_id


class Answer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    answer = db.Column(db.String(), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('question.id', ondelete="cascade"),
                            nullable=False)
    next_question = db.relationship(
        'Question', cascade="all, delete-orphan", uselist=False, backref='previous_answer',
        lazy=False, foreign_keys='Question.previous_answer_id')

    def __init__(self, answer, question_id):
        self.answer = answer
        self.question_id = question_id


db.create_all()


@app.route('/', methods=['GET'])
def verify():
    # when the endpoint is registered as a webhook, it must echo back
    # the 'hub.challenge' value it receives in the query arguments
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.challenge"):
        if not request.args.get("hub.verify_token") == os.environ["VERIFY_TOKEN"]:
            return "Verification token mismatch", 403
        return request.args["hub.challenge"], 200

    return "Hello world", 200


@cross_origin()
@app.route("/updatequestiontree", methods=['POST'])
def updatequestiontree():
    question_tree = json.loads(request.get_data())
    print(question_tree)
    result = update_tree(question_tree, None)
    if not result:
        return "Question Doesn't have answers!", 400
    return "", 200


@app.route("/pagesget", methods=['GET'])
def pagesget():
    pages = FbPage.query.all()
    pages_ids = list(map(lambda page: page.page_id, pages))
    return json.dumps(pages_ids)


@app.route("/workflows", methods=['GET'])
def workflows():
    page_id = request.args.get("page_id")
    questions = Question.query.filter_by(
        previous_answer_id=None, page_id=page_id).all()
    questions_ids = list(map(lambda question: question.id, questions))
    return json.dumps(questions_ids)


@cross_origin()
@app.route("/questionget", methods=['GET'])
def questionget():
    question_id = request.args.get("question_id")
    question = Question.query.filter_by(id=int(question_id)).first()
    serialized_question = serialize_question(question)
    return json.dumps(serialized_question)


@app.route("/questionadd", methods=['POST'])
def questionadd():
    question = request.form["question"]
    page_id = request.form["page_id"]
    previous_answer_id = request.form.get("previous_answer_id")
    question_entity = Question(question, page_id, previous_answer_id)
    db.session.add(question_entity)
    db.session.commit()

    return str(question_entity.id), 200


@app.route("/answeradd", methods=['POST'])
def answeradd():
    answer = request.form["answer"]
    question_id = int(request.form["question_id"])
    answer_entity = Answer(answer, question_id)
    db.session.add(answer_entity)
    db.session.commit()

    return str(answer_entity.id), 200


@app.route('/webhook', methods=['GET'])
def verifys():
    # when the endpoint is registered as a webhook, it must echo back
    # the 'hub.challenge' value it receives in the query arguments
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.challenge"):
        if not request.args.get("hub.verify_token") == os.environ["VERIFY_TOKEN"]:
            return "Verification token mismatch", 403
        return request.args["hub.challenge"], 200

    return "Hello world", 200


@app.route('/', methods=['POST'])
def webhook():

    # endpoint for processing incoming messaging events

    data = request.get_json()
    log(data)  # you may not want to log every incoming message in production, but it's good for testing

    if data["object"] == "page":   # make sure this is a page subscription

        for entry in data["entry"]:
            for messaging_event in entry["messaging"]:
                time = datetime.fromtimestamp(
                    messaging_event["timestamp"]/1000)

                if messaging_event.get("message"):     # someone sent us a message
                    received_message(messaging_event, time)

                elif messaging_event.get("delivery"):  # delivery confirmation
                    pass
                    # received_delivery_confirmation(messaging_event)

                elif messaging_event.get("optin"):     # optin confirmation
                    pass
                    # received_authentication(messaging_event)

                # user clicked/tapped "postback" button in earlier message
                elif messaging_event.get("postback"):
                    received_postback(messaging_event)

                else:    # uknown messaging_event
                    log("Webhook received unknown messaging_event: " + messaging_event)

    return "ok", 200


def received_message(event, time):

    # the facebook ID of the person sending you the message
    sender_id = event["sender"]["id"]
    # the recipient's ID, which should be your page's facebook ID
    recipient_id = event["recipient"]["id"]

    # could receive text or attachment but not both
    if "text" in event["message"]:
        message_text = event["message"]["text"]

        # parse message_text and give appropriate response
        if message_text == 'image' or message_text == 'Image':
            send_image_message(sender_id)

        elif message_text == 'file' or message_text == 'File':
            send_file_message(sender_id)

        elif message_text == 'audio' or message_text == 'Audio':
            send_audio_message(sender_id)

        elif message_text == 'video' or message_text == 'Video':
            send_video_message(sender_id)

        elif message_text == 'button' or message_text == 'Button':
            send_button_message(sender_id)

        elif message_text == 'generic' or message_text == 'Generic':
            send_generic_message(sender_id, recipient_id)

        elif message_text == 'share' or message_text == 'Share':
            send_share_message(sender_id)

        else:  # default case
            send_text_message(sender_id, "Echo: " + message_text)
            entry = Message(sender_id, recipient_id, time, message_text)
            db.session.add(entry)
            db.session.commit()
            my_user = FbUser.query.filter_by(user_id=sender_id).first()
            print(my_user)
            params = {
                "access_token": os.environ["PAGE_ACCESS_TOKEN"]
            }
            headers = {
                "Content-Type": "application/json"
            }
            if my_user == None:

                r = requests.get("https://graph.facebook.com/{}?fields=first_name,last_name,profile_pic".format(sender_id),
                                 params=params, headers=headers)
                json_user = json.loads(r.content)
                my_user = FbUser(sender_id,
                                 json_user["first_name"], json_user["last_name"], json_user["profile_pic"])
                db.session.add(my_user)
                db.session.commit()
            my_page = FbPage.query.filter_by(page_id=recipient_id).first()
            if my_page == None:
                r = requests.get(
                    "https://graph.facebook.com/{}".format(recipient_id), params=params, headers=headers)
                json_page = json.loads(r.content)
                my_page = FbPage(json_page["id"], json_page["name"])
                db.session.add(my_page)
                db.session.commit()
    elif "attachments" in event["message"]:
        message_attachments = event["message"]["attachments"]
        send_text_message(sender_id, "Message with attachment received")
    set_persistent_menu(sender_id)


# Message event functions
def send_text_message(recipient_id, message_text):

    # encode('utf-8') included to log emojis to heroku logs
    log("sending message to {recipient}: {text}".format(
        recipient=recipient_id, text=message_text.encode('utf-8')))

    message_data = json.dumps({
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "text": message_text
        }
    })

    call_send_api(message_data)


def send_generic_message(recipient_id, page_id):
    questions = Question.query.filter_by(page_id=page_id).limit(3).all()
    print("recipient_id")
    print(page_id)
    print("questions")
    print(questions)
    questions_buttons = []
    for question in questions:
        questions_buttons.append({
            "type": "postback",
            "title": question.question,
            "payload": str(question.id)
        })
    message_data = json.dumps({
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": "What do you want to do next?",
                    "buttons": questions_buttons
                }
            }
        }
    })

    log("sending template with choices to {recipient}: ".format(
        recipient=recipient_id))

    call_send_api(message_data)


def send_image_message(recipient_id):

    message_data = json.dumps({
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "attachment": {
                "type": "image",
                "payload": {
                    "url": "https://www.caritas.ch/fileadmin/_processed_/4/c/csm_caritas_news_yc-award_171127_31fa868713.jpg"
                }
            }
        }
    })

    log("sending image to {recipient}: ".format(recipient=recipient_id))

    call_send_api(message_data)


def send_file_message(recipient_id):

    message_data = json.dumps({
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "attachment": {
                "type": "file",
                "payload": {
                    "url": "https://asylex.ch/docs/asylverfahren_en.pdf"
                }
            }
        }
    })

    log("sending file to {recipient}: ".format(recipient=recipient_id))

    call_send_api(message_data)


def send_audio_message(recipient_id):

    message_data = json.dumps({
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "attachment": {
                "type": "audio",
                "payload": {
                    "url": "http://vochabular.ch/downloads/Audio/Kapitel2/3_Kapitel2_UebungAe_D/1.mp3"
                }
            }
        }
    })

    log("sending audio to {recipient}: ".format(recipient=recipient_id))

    call_send_api(message_data)


def send_video_message(recipient_id):

    message_data = json.dumps({
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "attachment": {
                "type": "video",
                "payload": {
                    "url": "http://techslides.com/demos/sample-videos/small.mp4"
                }
            }
        }
    })

    log("sending video to {recipient}: ".format(recipient=recipient_id))

    call_send_api(message_data)


def send_button_message(recipient_id):

    message_data = json.dumps({
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "button",
                    "text": "What do you want to do next?",
                    "buttons": [
                        {
                            "type": "web_url",
                            "url": "https://asylex.ch",
                            "title": "Asylex website"
                        },
                        {
                            "type": "postback",
                            "title": "Call Postback",
                            "payload": "Payload for send_button_message()"
                        }
                    ]
                }
            }
        }
    })

    log("sending button to {recipient}: ".format(recipient=recipient_id))

    call_send_api(message_data)


def send_share_message(recipient_id):

    # Share button only works with Generic Template
    message_data = json.dumps({
        "recipient": {
            "id": recipient_id
        },
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "generic",
                    "elements": [
                        {
                            "title": "Asylex link",
                            "subtitle": "free online legal aid on Swiss asylum law",
                            "image_url": "https://media-exp2.licdn.com/mpr/mpr/shrink_200_200/AAEAAQAAAAAAAAr8AAAAJDYyNGU1NWM4LTA4NzYtNGU4Yy1hNmY5LTA3MDAzOWRhZWFkNQ.png",
                            "buttons": [
                                {
                                    "type": "element_share"
                                }
                            ]
                        }
                    ]
                }

            }
        }
    })

    log("sending share button to {recipient}: ".format(recipient=recipient_id))

    call_send_api(message_data)


def received_postback(event):

    # the facebook ID of the person sending you the message
    sender_id = event["sender"]["id"]
    # the recipient's ID, which should be your page's facebook ID
    recipient_id = event["recipient"]["id"]

    # The payload param is a developer-defined field which is set in a postback
    # button for Structured Messages
    payload = event["postback"]["payload"]

    log("received postback from {recipient} with payload {payload}".format(
        recipient=recipient_id, payload=payload))

    if payload == 'Get Started':
        # Get Started button was pressed
        send_text_message(
            sender_id, "Welcome to the Asylex bot - Anything you type will be echoed back to you, except for the following keywords: image, file, audio, video, button, generic, share.")
    elif payload == 'Payload for send_button_message()':
        send_text_message(
            sender_id, "Welcome to the Asylex bot - Postback was called")
    else:
        # Notify sender that postback was successful
        # send_text_message(sender_id, "Welcome to the Asylex bot - Anything you type will be echoed back to you, except for the following keywords: image, file, audio, video, button, generic, share.")
        set_persistent_menu(sender_id)


def call_send_api(message_data):

    params = {
        "access_token": os.environ["PAGE_ACCESS_TOKEN"]
    }
    headers = {
        "Content-Type": "application/json"
    }

    r = requests.post("https://graph.facebook.com/v2.6/me/messages",
                      params=params, headers=headers, data=message_data)
    if r.status_code != 200:
        log(r.status_code)
        log(r.text)


def log(message):  # simple wrapper for logging to stdout on heroku
    print(message)
    sys.stdout.flush()

# import os, sys
# from flask import Flask, request
# from utils import wit_response, get_news_elements
# from pymessenger import Bot
# import requests,json

# app = Flask(__name__)


# bot = Bot(os.environ["PAGE_ACCESS_TOKEN"])
PAGE_ACCESS_TOKEN = os.environ.get('PAGE_ACCESS_TOKEN')


# @app.route('/', methods=['GET'])
# def verify():
# 	# Webhook verification
#     if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.challenge"):
#         if not request.args.get("hub.verify_token") == os.environ["VERIFY_TOKEN"]:
#             return "Verification token mismatch", 403
#         return request.args["hub.challenge"], 200
#     return "Hello world", 200


# @app.route('/', methods=['POST'])
# def webhook():
# 	data = request.get_json()
# 	log(data)

# 	if data['object'] == 'page':
# 		for entry in data['entry']:
# 			for messaging_event in entry['messaging']:

# 				# IDs
# 				sender_id = messaging_event['sender']['id']
# 				recipient_id = messaging_event['recipient']['id']

# 				if messaging_event.get('message'):
# 					# Extracting text message
# 					if 'text' in messaging_event['message']:
# 						messaging_text = messaging_event['message']['text']
# 					else:
# 						messaging_text = 'no text'

# 					# Echo
# 					#response = messaging_text

# 					# response = None
# 					# entity, value = wit_response(messaging_text)

# 					# if entity == 'newstype':
# 					# 	response = "OK. I will send you {} news".format(str(value))
# 					# elif entity == 'location':
# 					# 	response = "OK. So, you live in {0}. I will send you top headlines from {0}".format(str(value))

# 					# if response == None:
# 					# 	response = "Sorry, I didn't understand"

# 					categories = wit_response(messaging_text)
# 					elements = get_news_elements(categories)
# 					bot.send_generic_message(sender_id, elements)

# 				elif messaging_event.get('postback'):
# 					# HANDLE POSTBACKS HERE
# 					payload = messaging_event['postback']['payload']
# 					if payload ==  'SHOW_HELP':
# 						bot.send_quickreply(sender_id, HELP_MSG, news_categories)

# 	return "ok", 200

# def set_greeting_text():
# 	headers = {
# 		'Content-Type':'application/json'
# 		}
# 	data = {
# 		"setting_type":"greeting",
# 		"greeting":{
# 			"text":"Hi {{user_first_name}}! I am a news bot"
# 			}
# 		}
# 	ENDPOINT = "https://graph.facebook.com/v2.8/me/thread_settings?access_token=%s"%(PAGE_ACCESS_TOKEN)
# 	r = requests.post(ENDPOINT, headers = headers, data = json.dumps(data))
# 	print(r.content)

def set_persistent_menu(sender_id):
    headers = {
        'Content-Type': 'application/json'
    }

    persMenu = {
        "psid": sender_id,
        "get_started": {"payload": "GET_STARTED_PAYLOAD"},
        "persistent_menu": [
            {
                "locale": "default",
                "composer_input_disabled": "false"
            },

        ]
    }
    params = {
        "access_token": os.environ["PAGE_ACCESS_TOKEN"]
    }
    headers = {
        "Content-Type": "application/json"
    }

    r = requests.post("https://graph.facebook.com/v2.6/me/custom_user_settings",
                      params=params, headers=headers, data=json.dumps(persMenu))
    print("r.content")
    print(persMenu)
    print(r.content)


def serialize_question(question):
    answers = []
    if not question:
        return None
    if question.answers:
        for answer in question.answers:
            answers.append({
                "id": answer.id,
                "answer": answer.answer,
                "next_question": serialize_question(answer.next_question),
                "page_id": question.page_id
            })
    return {
        "question": question.question,
        "id": question.id,
        "answers": answers,
        "page_id": question.page_id
    }


def update_tree(question_tree, previous_answer_id):
    removed_nodes = question_tree.get(
        'removedNodes') if question_tree.get('removedNodes') else []
    for node in removed_nodes:
        if node["type"] == "Q":
            question = db.session.query(Question).filter(
                Question.id == node["id"]).first()
            db.session.delete(question)
        else:
            answer = db.session.query(Answer).filter(Answer.id == node["id"]).first()
            db.session.delete(answer)
    if question_tree.get("id"):
        Question.query.filter_by(id=int(question_tree["id"])).update(
            {"question": question_tree["title"], "page_id": question_tree["page_id"], "previous_answer_id": previous_answer_id})
    else:
        question = Question(
            question_tree["title"], question_tree["page_id"], previous_answer_id)
        db.session.add(question)
        db.session.commit()
        question_tree["id"] = question.id
    if not question_tree.get("children"):
        print(question_tree)
        return None
    for answer in question_tree["children"]:
        if answer.get("id"):
            Answer.query.filter_by(id=int(answer["id"])).update(
                {"answer": answer["title"],
                    "question_id": int(question_tree["id"])}
            )
        else:
            answer_entity = Answer(answer["title"], question_tree["id"])
            db.session.add(answer_entity)
            db.session.commit()
            answer["id"] = answer_entity.id
        if answer.get("children"):
            update_tree(answer["children"][0], int(answer["id"]))
    db.session.commit()


# def log(message):
# 	print(message)
# 	sys.stdout.flush()


# set_persistent_menu()
# set_greeting_text()
if __name__ == "__main__":
    app.run(debug=True)
