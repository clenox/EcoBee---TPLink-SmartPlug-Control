# Set up libraries

import datetime
from datetime import timedelta
import sys
import os
import importlib
import xml.etree.ElementTree as et
from time import sleep
import certifi
import requests
import urllib3
import json
from twilio.rest import Client
from pyHS100 import SmartPlug, Discover
from auth import creds
import traceback
import schedule
from schedule import schedule

looptime = 180
token_refresh_loops = 180 / looptime


def main():

    import schedule
    from schedule import schedule

# Input variables

# Determine which rooms are rotated (only allowed to be on one at a time)

    rotate_plugnames = ['OBED', 'LBED']

#  Temperature settings.  Setback is change in setting temp for Ohmhour DR event.  Must be a negative number.

    deadband = 0.2
    setback = -3.0

# Get authorizations

    auth_dict = creds()

# Fresh tokens on program start

    ecobee_token_response = ecobee_tokens(True, datetime.datetime.min)

    auth = ecobee_token_response[0]
    last_refresh_time = ecobee_token_response[1]

#  Set up Ohmconnect call

    http = urllib3.PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())

    oc = [False]

# initial timestamp

    timestamp = '{:%Y-%m-%d %H:%M:%S}'.format(datetime.datetime.now())

# Initial ecobee API call to populate room class
# TODO - refactor Ecobee API call and error handling (make consistent) as function
# TODO - Use /thermostatSummary URL to get Runtime Revision and refresh only when this changes

    try:

        thermostat_url = 'https://api.ecobee.com/1/thermostat?'
        payload = {'json': '{"selection":{"selectionType":"registered","includeSensors":"true"}}'}
        header = {'Content-Type': 'application/json;charset=UTF-8', 'Authorization': auth}

        response = requests.get(thermostat_url, headers=header, params=payload)

    except TimeoutError:

        err_string = (str(timestamp) + ' Timeout error in ecobee data call') + "\r"

        print(err_string)
        send_twilio_msg(err_string)

        log = open('log.txt', 'a+')
        log.write(err_string)
        log.close()

    data = response.json()

# Discover all temperature sensors

    tempdict = get_sensors(data)
    sensornames = list(tempdict.keys())

    if len(tempdict) == 0:

        print(data)
        sys.exit("no temperature sensors detected")

    else:

        pass

# Discover all plugs TODO consolidate into getplugs so it returns a dictionary of valid plug objects

    plugip = {}
    plugnames = []

    named_flag = False

    discover = get_plugs(plugip, plugnames, named_flag)

    plugip = discover[0]

    plugnames = discover[1]

    named_flag = True

    plugdict = {}

    for name in plugip:

        try:

            plugdict[name] = SmartPlug(plugip[name])

        except:

            pass

# Create list of valid rooms with both active sensors and plugs

    namelist = set(sensornames).intersection(plugnames)

# Define Room class

    class Room:

        def __init__(self, name, temp, status, temp_high, temp_low):
            self.name = name
            self.temp = temp
            self.status = status
            self.temp_high = temp_high
            self.temp_low = temp_low

# Initialize schedule and temperatures

    setdict = setpoints(timestamp)

# Define rooms and room dictionary

    roomdict = {}

    for name in namelist:

        roomdict[name] = Room(name, tempdict[name], 'OFF', setdict[name]+deadband, setdict[name])

# Initialize error counter & loop status

    sensor_error_count = 0

    last_loop_sched = True

    start_turn = 0

# Get last schedule modification time

    mtime = os.path.getmtime('schedule.py')

# Start main loop

    while True:

# Automatically reload schedule to capture changes

        mtime_now = os.path.getmtime('schedule.py')

        if mtime_now != mtime:

            importlib.reload(sys.modules['schedule'])
            from schedule import schedule
            print("Schedule Updated")

        else:

            pass

        mtime = mtime_now

# Token refresh

        ecobee_token_response = ecobee_tokens(False, last_refresh_time)

        last_refresh_time = ecobee_token_response[1]

# time handling

        timestamp = '{:%Y-%m-%d %H:%M:%S}'.format(datetime.datetime.now())

# Determine Schedule or Sleep mode

        setdict = setpoints(timestamp)

        setvals = []

        for name in namelist:

            setvals.append(setdict[name])

        if len(setvals) == setvals.count(-999):

            sched = False

        else:

            sched = True

# Schedule (active) mode

        if sched is True:

            # Token refresh

            ecobee_token_response = ecobee_tokens(False, last_refresh_time)

            auth = ecobee_token_response[0]
            last_refresh_time = ecobee_token_response[1]

# Call EcoBee API to get data
# TODO refactor to use thermostat Summary / Runtime Revision and change wehn values update.
# TODO at some point estimate temperature (ML?)

            try:

                thermostat_url = 'https://api.ecobee.com/1/thermostat?'
                payload = {'json': '{"selection":{"selectionType":"registered","includeSensors":"true"}}'}
                header = {'Content-Type': 'application/json;charset=UTF-8', 'Authorization': auth}

                response = requests.get(thermostat_url, headers=header, params=payload)

                data = response.json()

            except:

                err_string = (str(timestamp) + 'Error in ecobee data call') + "\r"

                print(err_string)

                sleep(30)

                continue

#  Update temperature readings with error handling

            tempdict = get_sensors(data)

            if len(tempdict) == 0:

                print(data)
                sensor_error_count = sensor_error_count + 1

                if sensor_error_count == 1:

                    send_twilio_msg("Warning - sensor temps not updating")

                elif sensor_error_count == 11:

                    send_twilio_msg("Temp reading failure.  Program exited.")
                    sys.exit("Temp reading failure.  Program exited.")

                else:

                    pass

                sleep(60)

                continue

            else:

                if sensor_error_count > 0:

                    send_twilio_msg("Sensor issue resolved")

                else:

                    pass

                sensor_error_count = 0

                pass

#  Get Ohmconnect status TODO use: get_OC(http)


            try:

                oc_url = auth_dict['ohmconnect_url']

                r = http.request('GET', oc_url)

                data = r.data

                root = et.fromstring(data)

                oc_txt = root[1].text

                if oc_txt == 'True':

                    oc_state = True

                else:

                    oc_state = False

            except:

                oc_state = False

# Determine Ohmconnect state and setback offset
# TODO use dequeue instead

            oc.insert(0,oc_state)
            last_oc = oc.pop()

            if oc_state == last_oc:

                offset = 0

            elif oc_state == True:

                offset = setback

            else:

                offset = -setback

# Decision logic and set booleans for switches
# Plug status is updated separately from state to reduce calls to plug endpoints and allow rotation of heater operation

            offline_list = []

            rotate_active = rotate_plugnames

            for name in namelist:

# Determine high and low setpoints for iteration based on deadband and offset

                roomdict[name].temp = tempdict[name]

                roomdict[name].temp_low = setdict[name]
                roomdict[name].temp_high = setdict[name]+deadband

                roomdict[name].temp_high = roomdict[name].temp_high + offset
                roomdict[name].temp_low = roomdict[name].temp_low + offset

#  Determine each room's status (On or Off)

                if schedule(name,'All') is True:

                    if roomdict[name].temp == 999:

                        print('Warning:  bad temp reading in ', name)

                        roomdict[name].status = roomdict[name].status

                    elif roomdict[name].temp <= roomdict[name].temp_low:

                        roomdict[name].status = "ON"

                    elif roomdict[name].temp > roomdict[name].temp_high:

                        roomdict[name].status = "OFF"

                    else:

                        roomdict[name].status = roomdict[name].status

                else:

                    roomdict[name].status = "OFF"
                    print(name," Room Is Off")

# Update state for plugs in rotation

                if not rotate_active:  # Handles the case of an empty rotate_active list

                    pass

                elif name in rotate_active:

#                    print(rotate_active)  # For debugging

                    status = roomdict[name].status

                    plug_rotation_return = plug_rotation(rotate_active, plugdict, name, status, start_turn)

                    roomdict[name].status = plug_rotation_return[0]
                    rotate_active = plug_rotation_return[1]

                else:

                    pass

#  Set plug state from status, with rediscovery on fail

                try:

                    plugdict[name].state = roomdict[name].status

                except:

                    plugip = get_plugs(plugip, plugnames, named_flag)[0]

                    try:

                        plugdict[name] = SmartPlug(plugip[name])

                    except:

                        offline_list.append(name)

            start_turn = plug_rotation_return[2]+1

#            statusmsg = str(offline_list)+" Offline" #TODO bring statusmsg back

# Write console & log

            stat_str = "\n" + "Timestamp: " + str(timestamp) + "\n" +"\n"
            log_str = str(timestamp) + ", "

            for name in namelist:

                stat_str += (str(name) + " Set: " + str(roomdict[name].temp_low) + " Temp: " +
                          str(roomdict[name].temp) + " Heat: " + str(roomdict[name].status) + "\n")

                log_str  += (str(name) + ", " + str(roomdict[name].temp_low) + ", " +
                          str(roomdict[name].temp) + ", " + str(roomdict[name].status) + ", ")

# TODO bring statusmsg back here too

#            stat_str += ("Mode: " + statusmsg + "\n" + "Ohmconnect Status: " + str(oc_txt))

#            log_str += ("Mode: " + statusmsg + ", " + "Ohmconnect Status: " + str(oc_txt) + "\n")


            log = open("log.txt", "a+")
            log.write(log_str)
            log.close()

            print(stat_str + "\r")

            last_loop_sched = True

# If outside of the schedule enter sleep mode.  No logging in sleep mode.

        elif last_loop_sched is True and sched is False:

# Turn all plugs off if possible

            for name in namelist:

                try:

                    if roomdict[name].status == 'ON':

                        plugdict[name].state = 'OFF'
                        roomdict[name].status = plugdict[name].state
                        print(name, 'turned off')

                    else:

                        pass

                except:

                    overrun_warn_msg = str('Warning, {0} offline -- could not be turned off automatically'.format(name))

                    send_twilio_msg(overrun_warn_msg)
                    print(overrun_warn_msg)

            print('Sleep Mode')

            last_loop_sched = False

        else:

            pass

        sleep(looptime)

        continue

def get_plugs(plugip, plugnames, named_flag):

    try:

        for dev in Discover.discover():
            plugobj = SmartPlug(dev)
            plugip[plugobj.alias] = dev

            if named_flag is False:

                plugnames.append(plugobj.alias)

            else:

                pass

    except:

        plugip = {}
        plugnames = []
        send_twilio_msg('Warning - plug discovery failed')
        traceback.print_exc()


    return [plugip, plugnames]

def set_plug(name, state, plugdict, plugip, plugnames):

# TODO Not currently used!  Trying to encapsulate state call & error checking to pull it out of main
# This is a mess!  Need to consolidate get_plugs and probably put everything in a big dict to pass across fxns

# name is the name of the room / plug
# state is the desired state ('ON' or 'OFF')

    named_flag = True

    plugips = plugip

    try:

        plugdict[name].state = state

    except:

        plugips = get_plugs(plugips, plugnames, named_flag)[0]

        try:

            plugdict[name] = SmartPlug(plugips[name])

        except:

            print("Communication error in ", name)

    return

def get_sensors(data):

    sensornames = []
    sensortemps = []
    temps = []
    tempdict = {}
    sensor_detect = True

    try:

        for i in range(len(data['thermostatList'][0]['remoteSensors'])):
            sensornames.append(data['thermostatList'][0]['remoteSensors'][i]['name'])
            sensortemps.append(data['thermostatList'][0]['remoteSensors'][i]['capability'][0]['value'])

    except:

        sensor_detect = False

    if sensor_detect is True:

        for item in sensortemps:

            try:

                tval = float(item) / 10

            except ValueError:

                tval = 999

            temps.append(tval)

        tempdict = dict(zip(sensornames, temps))

    else:

        pass

    return tempdict


def ecobee_tokens(loop_count_reset, last_refresh_time):

    app_key = creds()['ecobee_apikey']

    retry_count = 0

    token_interval_time = timedelta(minutes=30) # If less than looptime, refresh interval will be looptime interval
                                                # Tokens expire after 3600 seconds
    current_time = datetime.datetime.now()

    elapsed_time = current_time - last_refresh_time

    # open token file store & retrieve current tokens

    f = open("tokens.txt", "r")

    token_str = str(f.read())

    f.close()

    token_list = token_str.split(",")

    try:

        auth = token_list[1]+' '+token_list[0]

    except IndexError:

        send_twilio_msg('Heatrun Error -- Bad Ecobee Token File')
        print("bad tokens:", token_str)
        sys.exit('Token File Read Error')

    while retry_count <= 10:

        if elapsed_time >= token_interval_time or loop_count_reset is True:

            try:

                refresh_token = token_list[2]

            except IndexError:

                send_twilio_msg('Heatrun Error -- Bad Ecobee Token File')
                sys.exit('Token File Read Error')

            token_url = 'https://api.ecobee.com/token?'
            payload = {'grant_type': 'refresh_token', 'refresh_token': refresh_token, 'client_id': app_key}

            try:

                r_refresh = requests.post(token_url, params=payload)

                r_refresh_dict = json.loads(r_refresh.text)

                if r_refresh.status_code == requests.codes.ok:

                    token_type = r_refresh_dict['token_type']
                    access_token = r_refresh_dict['access_token']
                    refresh_token = r_refresh_dict['refresh_token']

                    auth_log = access_token + "," + token_type + "," + refresh_token

                    auth = token_type + ' ' + access_token

                    # Check tokens are received

                    if len(auth_log) == 0:

                        raise ValueError("Empty token refresh")

                    else:

                        pass

                    # write new tokens to file store

                    f = open("tokens.txt", "w+")
                    f.truncate()
                    f.write(auth_log)
                    f.close()

                    retry_count = 0
                    last_refresh_time = datetime.datetime.now()

                    break

                else:

                    raise ValueError(r_refresh.status_code)

            except:

                if retry_count == 0:

                    retry_count = retry_count + 1
                    send_twilio_msg('Warning - Ecobee token issue.  Retrying for 10 minutes.')
                    sleep(60)

                elif retry_count <= 10:

                    retry_count = retry_count + 1
                    sleep(60)

                else:

                    send_twilio_msg('Ecobee token refresh failed - restart manually!')
                    sys.exit('token refresh error')

                continue

        else:

            break

    return (auth, last_refresh_time)


def send_twilio_msg(alert_msg):

    twilio_sid = creds()['twilio_sid']
    twilio_token = creds()['twilio_token']
    twilio_from = creds()['twilio_from']
    twilio_to = creds()['twilio_to']

    client = Client(twilio_sid, twilio_token)

    try:

        message = client.messages.create(
            from_=twilio_from,
            body=alert_msg,
            to=twilio_to
        )

    except:

        print(alert_msg,'-- Sending SMS failed, check internet connection')

    return True


def setpoints(timestamp):

    from schedule import schedule

    hourstart = int(float(timestamp[11:13]) + float(timestamp[14:16]) / 60)

    mbed_tlow = schedule('MBED', hourstart)
    lbed_tlow = schedule('LBED', hourstart)
    obed_tlow = schedule('OBED', hourstart)

    setdict = {'MBED': mbed_tlow, 'LBED': lbed_tlow, 'OBED': obed_tlow}

    return setdict


def plug_rotation(rotate_plugnames, plugdict, plugname, plugstatus, start_turn):

    turn = start_turn

    plugnames = rotate_plugnames

    if plugstatus == "OFF":

        plugnames = plugnames.remove(plugname)
        status = "OFF"

        print('early return')

        return status, plugnames, turn

    else:

        pass

    if turn >= len(plugnames):

        turn = 0

    else:

        pass

    print(turn)

    if plugname == plugnames[turn]:

        try:

            current = plugdict[plugname].state

            if current == 'OFF':

                status = 'ON'

            else:

                status = current

        except:

            print("Communications error in", plugname)
            status = 'OFF'
            plugnames[turn].remove()

    else:

        status = 'OFF'

    return status, plugnames, turn

def get_OC(http):

    # Determine Ohmconnect state
    # Retrieve unique Ohmconnect url from credentials module (note - you must modify this with your unique URL)

    OC_state = 'Initialize'

    OC_url = creds()['OC_url']

    try:

        r = http.request('GET', OC_url)

        data = r.data

        root = et.fromstring(data)

        OC_state = root[1].text

    except:

        OC_state = 'False'

    return OC_state

if __name__ == "__main__":

    main()
