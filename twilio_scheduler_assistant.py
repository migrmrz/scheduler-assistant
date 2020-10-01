from flask import Flask, request, jsonify
from apiclient.discovery import build
from apiclient import errors
import pickle
from datetime import timedelta, datetime, timezone
from dateutil import tz
import os
import json
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)


@app.route("/book_appt", methods=['POST'])
def book_appt():
    """
        Incoming autopilot task: book_appointments
        Routes to: complete_appt and notify_no_availability
    """
    memory = json.loads(request.form.get('Memory'))
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")

    answers = memory[
        'twilio']['collected_data']['book_appt']['answers']

    appt_time = answers['appt_time']['answer']
    appt_date = answers['appt_date']['answer']

    start_time_str = appt_date + ' ' + appt_time
    start_time_obj = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M')
    tzinfo = tz.gettz(os.environ.get("LOCAL_TIMEZONE"))
    start_time_obj = start_time_obj.replace(tzinfo=tzinfo)

    appt_type = int(answers['appt_type']['answer'])

    duration = get_details_from_sevice_type(appt_type)[0]

    if check_availability(calendar_id, start_time_obj, duration):
        response = {
            "actions": [
                {
                    "redirect": "task://complete_booking"
                },
                {
                    "remember": {
                        "appt_type": appt_type,
                        "appt_time": appt_time,
                        "appt_date": appt_date,
                    }
                }
            ]
        }
    else:
        response = {
            "actions": [
                {
                    "redirect": "task://notify_no_availability"
                }
            ]
        }

    return jsonify(response)


@app.route("/complete_booking", methods=['POST'])
def complete_booking():
    """
        Incoming autopilot task: complete_booking
        Routes to: confirm_booking
    """
    memory = json.loads(request.form.get('Memory'))
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")
    answers = memory[
        'twilio']['collected_data']['complete_appt']['answers']

    appt_dog_name = answers['appt_dog_name']['answer']
    appt_email = answers['appt_email']['answer']
    appt_type = memory['appt_type']
    appt_time = memory['appt_time']
    appt_date = memory['appt_date']

    start_time_str = appt_date + ' ' + appt_time
    start_time_obj = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M')
    tzinfo = tz.gettz(os.environ.get("LOCAL_TIMEZONE"))
    start_time_obj = start_time_obj.replace(tzinfo=tzinfo)

    create_event(
        calendar_id,
        appt_dog_name,
        appt_email,
        start_time_obj,
        appt_type
    )

    response = {
        "actions": [
            {
                "redirect": "task://confirm_booking"
            }
        ]
    }

    return jsonify(response)


@app.route("/cancel_appt", methods=['POST'])
def cancel_appt():
    """
        Incoming autopilot task: cancel_appointments
        Routes to: confirm_cancel or error response message
    """
    memory = json.loads(request.form.get('Memory'))
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")

    if memory['cancel_appt'] == "in_progress":

        if 'appt_event_id' in memory:

            event_id = memory['appt_event_id']
            appt_email = memory['appt_email']
            cancel_result = cancel_event(calendar_id, event_id)

            if cancel_result:
                response = {
                    "actions": [
                        {
                            "redirect": "task://confirm_cancel"
                        }
                    ]
                }
            else:
                response = {
                    "actions": [
                        {
                            "redirect": "task://notify_no_event_found"
                        }
                    ]
                }

        else:
            response = {
                "actions": [
                    {
                        "redirect": "task://complete_cancel"
                    }
                ]
            }

    elif memory['cancel_appt'] == "list_needed":
        answers = memory[
            'twilio']['collected_data']['cancel_appt']['answers']
        appt_email = answers['appt_email']['answer']
        next_event = get_next_event_from_user(calendar_id, appt_email)
        if next_event is None:
            response = {
                "actions": [
                    {
                        "redirect": "task://notify_no_event_found"
                    }
                ]
            }
        else:
            event_id = next_event['id']
            response = {
                "actions": [
                    {
                        "remember": {
                            "appt_event_id": event_id,
                            "appt_email": appt_email,
                            "cancel_appt": "in_progress"
                        }
                    },
                    {
                        "redirect": "https://85c5c9a5ca22.ngrok.io/cancel_appt"
                    }
                ]
            }

    return jsonify(response)


@app.route("/change_appt", methods=['POST'])
def change_appt():
    """
        Incoming task: change_appointments.
        Listens: book_appointments, list_appointments, goodbye
    """
    memory = json.loads(request.form.get('Memory'))
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")

    if memory['change_appt'] == "in_progress":

        if 'change_appt' in memory['twilio']['collected_data']:
            # list_appointment has been executed before and new appt data has
            # been collected
            answers = memory[
                'twilio']['collected_data']['change_appt']['answers']
            event_id = memory['appt_event_id']
            appt_email = memory['appt_email']

            appt_time = answers['appt_time']['answer']
            appt_date = answers['appt_date']['answer']
            appt_type = int(answers['appt_type']['answer'])

            start_time_str = appt_date + ' ' + appt_time
            start_time_obj = datetime.strptime(
                start_time_str, '%Y-%m-%d %H:%M')
            tzinfo = tz.gettz(os.environ.get("LOCAL_TIMEZONE"))
            start_time_obj = start_time_obj.replace(tzinfo=tzinfo)

            update_event(
                event_id, calendar_id, start_time_obj, appt_type
            )

            response = {
                "actions": [
                    {
                        "remember": {
                            "appt_event_id": event_id,
                            "change_appt": "done"
                        }
                    },
                    {
                        "redirect": "task://confirm_change"
                    }
                ]
            }
        elif 'appt_event_id' in memory:
            response = {
                "actions": [
                    {
                        "redirect": "task://complete_change"
                    }
                ]
            }
        else:
            # Events haven't been listed before
            response = {
                "actions": [
                    {
                        "redirect": "task://lookup_for_change"
                    }
                ]
            }

    elif memory['change_appt'] == "list_needed":
        answers = memory['twilio']['collected_data']['change_appt']['answers']
        appt_email = answers['appt_email']['answer']
        next_event = get_next_event_from_user(calendar_id, appt_email)
        print(next_event)
        if next_event is None:
            response = {
                "actions": [
                    {
                        "redirect": "task://notify_no_event_found"
                    }
                ]
            }
        else:
            event_id = next_event['id']
            response = {
                "actions": [
                    {
                        "remember": {
                            "appt_event_id": event_id,
                            "change_appt": "in_progress"
                        }
                    },
                    {
                        "redirect": "task://complete_change"
                    }
                ]
            }

    return jsonify(response)


@app.route("/list_appt", methods=['POST'])
def list_appt():
    """
        Incoming task: list_appointments.
        Listens: cancel_appointments, change_appointments, goodbye
    """
    memory = json.loads(request.form.get('Memory'))
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")

    answers = memory[
        'twilio']['collected_data']['list_appt']['answers']

    appt_email = answers['appt_email']['answer']

    next_event = get_next_event_from_user(calendar_id, appt_email)

    if next_event is None:
        response = {
            "actions": [
                {
                    "redirect": "task://notify_no_event_found"
                }
            ]
        }

    else:
        datetime_str = next_event['start']['dateTime']
        datetime_obj = datetime(
            int(datetime_str[:4]),
            int(datetime_str[5:7]),
            int(datetime_str[8:10])
        )
        day_str = datetime_obj.strftime("%m/%d/%Y")
        time_str = datetime_str[11:16]
        dog_name = next_event['summary'].split("'s appointment")[0]

        event_id = next_event['id']

        response = {
            "actions": [
                {
                    "say":
                    "Your next appointment is on {} at {} for {}. I can always"
                    " help you reschedule or cancel it."
                    .format(day_str, time_str, dog_name)
                },
                {
                    "listen":
                        {
                            "tasks": [
                                "cancel_appointments",
                                "change_appointments",
                                "goodbye"
                            ]
                        }
                },
                {
                    "remember":
                        {
                            "appt_event_id": event_id,
                            "appt_email": appt_email
                        }
                }
            ]
        }

    return jsonify(response)


def get_details_from_sevice_type(service_type):
    """
        Returns a duration value in minutes and description based on a type of
        service as input.
        Service types:
            1. Bath (60 mins)
            2. Bath with haircut (120 mins)
            3. Bath with brush (90 mins)
    """
    if service_type == 1:
        return 60, "Bath"
    elif service_type == 2:
        return 120, "Bath with haircut"
    elif service_type == 3:
        return 90, "Bath with brush"


def create_service():
    """
        Creates and returns a Google Calendar service from a pickle file
        previously generated.
    """

    with open("token.pickle", "rb") as token:
        credentials = pickle.load(token)

    service = build("calendar", "v3", credentials=credentials)

    return service


def check_availability(calendar_id, start_time, duration):
    """
        Checks if there is an event already created at the specific date and
        time provided. Returns True if the spot is available.
        Parameters:
            - calendar_id
            - start_time
            - duration
        Returns: boolean. True if the spot is available.
    """
    time_min = start_time.astimezone(tz.tzutc()).isoformat()
    time_max = (start_time + timedelta(minutes=duration)) \
        .astimezone(tz.tzutc()).isoformat()

    service = create_service()

    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max
    ).execute()

    return True if events_result['items'] == [] else False


def get_next_event_from_user(calendar_id, appt_email):
    """
        Returns a list of all the events on a specific calendar from the
        next 30 days.
        Parameters:
            - calendarId
            - email
        Returns: Dict structure with the nearest event in case one is found.
        None is no event was found
    """

    time_min = datetime.now(timezone.utc).isoformat()
    time_max = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    service = create_service()

    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents="True",
        orderBy="startTime"
    ).execute()

    event_result = None

    for item in events_result['items']:
        event_start = datetime.strptime(
            item['start']['dateTime'],
            "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None)
        # There should always be an attendee and it will always be only one
        if 'attendees' in item \
                and item['attendees'][0].get('email') == appt_email \
                and event_start > datetime.now():
            event_result = item
            break  # Because we will only return the first occurence

    return event_result


def create_event(
        calendar_id, dog_name, email, notes, start_time, service_type):
    """
        Creates an event on the calendar.
        Parameters:
            - name of the dog(s) for the appointment
            - email of the attendee for email confirmation
            - notes. Any particular details that want to be noted
            - start_time in datetime.datetime format
            - service_type which also determines the appointment duration in
            minutes for the end_time calculation
        Returns: Event structure as confirmation
    """

    summary = "{}'s appointment".format(dog_name)
    location = "Pet Bath and Beyond, 905 Kranzel Dr, Camp Hill, PA 17011, USA"

    duration, type_description = get_details_from_sevice_type(type)

    end_time = start_time + timedelta(minutes=duration)

    event = {
        'summary': summary,
        'location': location,
        'description': type_description,
        'start': {
            'dateTime': start_time.strftime("%Y-%m-%dT%H:%M:%S"),
            'timeZone': os.environ.get("LOCAL_TIMEZONE")
        },
        'end': {
            'dateTime': end_time.strftime("%Y-%m-%dT%H:%M:%S"),
            'timeZone': os.environ.get("LOCAL_TIMEZONE")
        },
        'attendees': [
            {'email': email},
        ],
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'popup', 'minutes': 10}
            ],
        },
    }

    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID")

    service = create_service()

    create_event = service.events().insert(
        calendarId=calendar_id,
        body=event,
        sendNotifications=True
    ).execute()

    return create_event


def update_event(event_id, calendar_id, start_time, type):
    """
        Updates event.
        Parameters:
            - calendar_id
            - event_id
            - start_time in a datetime.datetime format
            - end_time in a datetime.datetime format
        Returns: Event structure as confirmation
    """

    if type == 1:
        duration = 90
        type_description = "Bath"
    elif type == 2:
        duration = 150
        type_description = "Bath with haircut"
    elif type == 3:
        duration = 120
        type_description = "Bath with brush"

    end_time = start_time + timedelta(minutes=duration)

    body = {
        'description': type_description,
        'start': {
            'dateTime': start_time.strftime("%Y-%m-%dT%H:%M:%S"),
            'timeZone': os.environ.get("LOCAL_TIMEZONE")
        },
        'end': {
            'dateTime': end_time.strftime("%Y-%m-%dT%H:%M:%S"),
            'timeZone': os.environ.get("LOCAL_TIMEZONE")
        }
    }

    service = create_service()

    update_event = service.events().patch(
        calendarId=calendar_id,
        eventId=event_id,
        body=body,
        sendUpdates='all'
    ).execute()

    return update_event


def cancel_event(calendar_id, event_id):
    """
        Deletes an event from the calendar. Appointment cancellation.
        Parameters:
            - event_id
            - calendar_id
        Returns: boolean. True if service was cancelled correctly or False if
        there was an error.
    """
    service = create_service()

    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id)\
            .execute()
    except errors.HttpError as e:
        print(e)
        return False
    else:
        return True


if __name__ == "__main__":
    app.run(debug=True)
