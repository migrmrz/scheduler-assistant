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

    if 'appt_id' in memory and memory['appt_id'] != "":
        # User left an unfinished booking in the conversation due to an error
        cancel_event(calendar_id, memory['appt_id'])
    # Delete draft events that have more than 5 minutes of being created
    delete_draft_events(calendar_id)

    answers = memory[
        'twilio']['collected_data']['book_appt']['answers']

    appt_time = answers['appt_time']['answer']
    appt_date = answers['appt_date']['answer']

    start_time_str = appt_date + ' ' + appt_time
    start_time_obj = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M')
    tzinfo = tz.gettz(os.environ.get("LOCAL_TIMEZONE"))
    start_time_obj = start_time_obj.replace(tzinfo=tzinfo)

    appt_type = int(answers['appt_type']['answer'])

    available_event_id = check_availability(
        calendar_id, start_time_obj, appt_type)

    if available_event_id:
        response = {
            "actions": [{
                    "redirect": "task://complete_booking"
                },
                {
                    "remember": {
                        "appt_id": available_event_id
                    }
                }
            ]
        }
    else:
        response = {
            "actions": [{
                "redirect": "task://notify_no_availability"
            }]
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
    event_id = memory['appt_id']

    event = update_event(
        event_id=event_id,
        calendar_id=calendar_id,
        dog_name=appt_dog_name,
        start_time='',
        service_type='',
        email=appt_email)

    if event['status'] == 'cancelled':
        # Cancelled due to time limit exceeded during reservation and another
        # user started a booking process
        response = {
            "actions": [{
                "say": "I'm sorry. The time limit to confirm the reservation "
                "has been exceeded. Please try again."
            }, {
                "remember": {
                    "appt_id": ""
                }
            }, {
                "redirect": "task://book_appointments"
            }]
        }
    else:
        response = {
            "actions": [{
                "redirect": "task://confirm_booking"
            }]
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

        if 'collected_data' in memory['twilio'] and \
                'change_appt' in memory['twilio']['collected_data']:
            # list_appointment hasn't been executed before and new appt data
            # has been collected
            answers = memory[
                'twilio']['collected_data']['change_appt']['answers']
            event_id = memory['appt_event_id']

            appt_time = answers['appt_time']['answer']
            appt_date = answers['appt_date']['answer']
            appt_type = int(answers['appt_type']['answer'])

            start_time_str = appt_date + ' ' + appt_time
            start_time_obj = datetime.strptime(
                start_time_str, '%Y-%m-%d %H:%M')
            tzinfo = tz.gettz(os.environ.get("LOCAL_TIMEZONE"))
            start_time_obj = start_time_obj.replace(tzinfo=tzinfo)

            update_event(
                event_id=event_id,
                calendar_id=calendar_id,
                dog_name='',
                start_time=start_time_obj,
                service_type=appt_type,
                email=''
            )

            response = {
                "actions": [{
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
                "actions": [{
                    "redirect": "task://complete_change"
                }]
            }
        else:
            # Events haven't been listed before
            response = {
                "actions": [{
                    "redirect": "task://lookup_for_change"
                }]
            }

    elif memory['change_appt'] == "list_needed":
        answers = memory['twilio']['collected_data']['change_appt']['answers']
        appt_email = answers['appt_email']['answer']
        next_event = get_next_event_from_user(calendar_id, appt_email)
        print(next_event)
        if next_event is None:
            response = {
                "actions": [{
                    "redirect": "task://notify_no_event_found"
                }]
            }
        else:
            event_id = next_event['id']
            response = {
                "actions": [{
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


def check_availability(calendar_id, start_time, service_type):
    """
        Checks if there is an event already created at the specific date and
        time provided and creates a temporary one to reserve the spot.
        Parameters:
            - calendar_id
            - start_time
            - service_type
        Returns: id of the created event or None if the spot is not available.
    """
    duration, type_description = get_details_from_sevice_type(service_type)
    time_min = start_time.astimezone(tz.tzutc()).isoformat()
    time_max = (start_time + timedelta(minutes=duration)) \
        .astimezone(tz.tzutc()).isoformat()

    service = create_service()

    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max
    ).execute()

    event_id = None

    if events_result['items'] == []:
        # Creates a draft event to reserve the spot after checking availability
        event = create_event(
            calendar_id, start_time, duration, type_description)
        event_id = event['id']

    return event_id


def get_next_event_from_user(calendar_id, appt_email):
    """
        Returns a list of all the events on a specific calendar in the next 30
        days.
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


def create_event(calendar_id, start_time, duration, type_description):
    """
        Creates an event on the calendar.
        Parameters:
            - calendar_id
            - start_time in datetime.datetime format
            - duration of the appointment that will be used to calculate the
            end time of the event
            - type_description
        Returns: Event structure as confirmation
    """
    location = "Pet Bath and Beyond, 905 Kranzel Dr, Camp Hill, PA 17011, USA"
    end_time = start_time + timedelta(minutes=duration)

    event = {
        'location': location,
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

    create_event = service.events().insert(
        calendarId=calendar_id,
        body=event,
        sendNotifications=True
    ).execute()

    return create_event


def update_event(
        event_id, calendar_id, dog_name, start_time, service_type, email):
    """
        Updates event.
        Parameters:
            - calendar_id
            - event_id
            - start_time in a datetime.datetime format
            - end_time in a datetime.datetime format
        Returns: Event structure as confirmation
    """
    summary = "{}'s appointment".format(dog_name)

    if start_time == '' and service_type == '':
        # It is a confirmation update that doesn't need to change time and type
        body = {
            'summary': summary,
            'attendees': [
                {'email': email},
            ],
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 30}
                ],
            }
        }
    else:
        # It is a modification of event requested by the user
        duration, type_description = get_details_from_sevice_type(service_type)
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


def cancel_event(calendar_id, event_id, service=None):
    """
        Deletes an event from the calendar. Appointment cancellation.
        Parameters:
            - event_id
            - calendar_id
            - service
        Returns: boolean. True if service was cancelled correctly or False if
        there was an error.
    """
    if not service:
        service = create_service()

    try:
        service.events().delete(calendarId=calendar_id, eventId=event_id)\
            .execute()
    except errors.HttpError as e:
        print(e)
        return False
    else:
        return True


def delete_draft_events(calendar_id):
    """
        Deletes events with no email assigned in a period of 60 days and has
        been more than 5 minutes of being created. This means that:
            - A user started a booking process, the spot was reserved but
            ended the conversation halfway through (fallback action or simply
            left) or
            - A user started a booking process but took more than 5 minutes to
            fill all the information to get a confirmation and another user
            started another process
        Parameter:
            - calendar_id
    """
    time_min = datetime.now(timezone.utc).isoformat()
    time_max = (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()

    service = create_service()

    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents="True",
        orderBy="startTime"
    ).execute()

    for item in events_result['items']:
        start_time = datetime.strptime(
            item['created'], "%Y-%m-%dT%H:%M:%S.%f%z")
        time_diff_delta = datetime.now(timezone.utc) - start_time
        time_diff_mins = time_diff_delta.total_seconds() / 60
        if 'attendees' not in item and time_diff_mins > 5:
            cancel_event(calendar_id, item['id'], service)


if __name__ == "__main__":
    app.run(debug=True)
