#!/usr/bin/python
"""Solis cloud API data fetcher."""
import base64
import datetime
import hashlib
import hmac
import json
import logging
import logging.config
import urllib
import urllib.parse
import socket
import time
import traceback
from influxdb import InfluxDBClient
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request
import requests
import schedule


# Not all keys are available depending on your setup
COLLECTED_DATA = {
    'DC_Voltage_PV1': '1a',  #
    'DC_Voltage_PV2': '1b',  #
    'DC_Voltage_PV3': '1c',  #
    'DC_Voltage_PV4': '1d',  #
    'DC_Current1': '1j',  #
    'DC_Current2': '1k',  #
    'DC_Current3': '1l',  #
    'DC_Current4': '1m',  #
    'AC_Voltage': '1ah',  #
    'AC_Current': '1ak',  #
    'AC_Power': '1ao',
    'AC_Frequency': '1ar',
    'DC_Power_PV1': '1s',
    'DC_Power_PV2': '1t',
    'DC_Power_PV3': '1u',
    'DC_Power_PV4': '1v',
    'Inverter_Temperature': '1df',
    'Daily_Generation': '1bd',
    'Monthly_Generation': '1be',
    'Annual_Generation': '1bf',
    'Total_Generation': '1bc',
    'Generation_Last_Month': '1ru',
    'Power_Grid_Total_Power': '1bq',  #
    'Total_On_grid_Generation': '1bu',
    'Total_Energy_Purchased': '1bv',  #
    'Consumption_Power': '1cj',
    'Consumption_Energy': '1cn',
    'Daily_Energy_Used': '1co',
    'Monthly_Energy_Used': '1cp',
    'Annual_Energy_Used': '1cq',
    'Battery_Charge_Percent': '1cv'
}


def do_work():
    """worker loop"""

    # solis cloud api config
    api_key_id = ""  # os.environ['SOLIS_CLOUD_API_KEY_ID']
    api_key_pw = "".encode("utf-8")  # os.environ['SOLIS_CLOUD_API_KEY_SECRET'].encode("utf-8")
    domain = "https://www.soliscloud.com"  # os.environ['SOLIS_CLOUD_API_URL']
    port = "13333"  # os.environ['SOLIS_CLOUD_API_PORT']
    url = "{}:{}".format(domain, port)
    # lan = os.environ['GINLONG_LANG']
    device_id = 0  # os.environ['SOLIS_CLOUD_API_INVERTER_ID']

    # == Constants ===============================================================
    http_function = "POST"
    mime_content_type = "application/json"
    endpoint_station_list = "/v1/api/userStationList"
    endpoint_inverter_list = "/v1/api/inverterList"
    endpoint_inverter_detail = "/v1/api/inverterDetail"

    # == Output ==================================================================

    # Influx settings
    influx = ""  # os.environ['USE_INFLUX']
    influx_database = ""  # os.environ['INFLUX_DATABASE']
    influx_server = ""  # os.environ['INFLUX_SERVER']
    influx_port = ""  # os.environ['INFLUX_PORT']
    influx_user = ""  # os.environ['INFLUX_USER']
    influx_password = ""  # os.environ['INFLUX_PASSWORD']
    influx_measurement = ""  # os.environ['INFLUX_MEASUREMENT']

    # pvoutput
    pvoutput = ""  # os.environ['USE_PVOUTPUT']
    pvoutput_api = ""  # os.environ['PVOUTPUT_API_KEY']
    pvoutput_system = ""  # os.environ['PVOUTPUT_SYSTEM_ID']

    # MQTT
    mqtt = ""  # os.environ['USE_MQTT']
    mqtt_client = ""  # os.environ['MQTT_CLIENT_ID']
    mqtt_server = ""  # os.environ['MQTT_SERVER']
    mqtt_username = ""  # os.environ['MQTT_USERNAME']
    mqtt_password = ""  # os.environ['MQTT_PASSWORD']

    ###
    # == prettify json output ====================================================
    def prettify_json(input_json) -> str:
        """prettifies json for better output readability"""
        return json.dumps(json.loads(input_json), indent=2)

    # == post ====================================================================
    def execute_request(target_url, data, headers) -> str:
        """execute request and handle errors"""
        if data != "":
            post_data = data.encode("utf-8")
            request = Request(target_url, data=post_data, headers=headers)
        else:
            request = Request(target_url)
        error_string = ""
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read()
                body_content = body.decode("utf-8")
                logging.debug("Decoded content: " + body_content)
                return body_content
        except HTTPError as error:
            error_string = str(error.status) + ": " + error.reason
        except URLError as error:
            error_string = str(error.reason)
        except TimeoutError:
            error_string = "Request timed out"
        except socket.timeout:
            error_string = "Socket timed out"
        except Exception as ex:  # pylint: disable=broad-except
            error_string = "urlopen exception: " + str(ex)
            traceback.print_exc()

        logging.error(target_url + " -> " + error_string)
        time.sleep(60)  # retry after 1 minute
        return "ERROR"

    # == get_solis_cloud_data ====================================================
    def get_solis_cloud_data(url_part, data) -> str:
        """get solis cloud data"""
        md5 = base64.b64encode(hashlib.md5(data.encode("utf-8")).digest()).decode("utf-8")
        while True:
            now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
            encrypt_str = (
                    http_function + "\n"
                    + md5 + "\n"
                    + mime_content_type + "\n"
                    + now + "\n"
                    + url_part
            )
            hmac_obj = hmac.new(
                api_key_pw,
                msg=encrypt_str.encode("utf-8"),
                digestmod=hashlib.sha1,
            )
            authorization = (
                    "API "
                    + api_key_id
                    + ":"
                    + base64.b64encode(hmac_obj.digest()).decode("utf-8")
            )
            headers = {
                "Content-MD5": md5,
                "Content-Type": mime_content_type,
                "Date": now,
                "Authorization": authorization,
            }
            data_content = execute_request(url + url_part, data, headers)
            logging.debug(url + url_part + "->" + prettify_json(data_content))
            if data_content != "ERROR":
                return data_content

    # == get_inverter_list_body ==================================================
    def get_inverter_list_body() -> str:
        """get inverter list body"""
        body = '{"userid":"' + api_key_id + '"}'
        data_content = get_solis_cloud_data(endpoint_station_list, body)
        station_info = json.loads(data_content)["data"]["page"]["records"][0]
        station_id = station_info["id"]

        body = '{"stationId":"' + station_id + '"}'
        data_content = get_solis_cloud_data(endpoint_inverter_list, body)
        inverter_info = json.loads(data_content)["data"]["page"]["records"][
            device_id
        ]
        inverter_id = inverter_info["id"]
        inverter_sn = inverter_info["sn"]

        body = '{"id":"' + inverter_id + '","sn":"' + inverter_sn + '"}'
        logging.debug("body: %s", body)
        return body

    # == MAIN ====================================================================
    def get_inverter_data():
        inverter_list_body = get_inverter_list_body()

        data_content = get_solis_cloud_data(endpoint_inverter_detail, inverter_list_body)
        inverter_detail_data = json.loads(data_content)["data"]

        return inverter_detail_data

    def write_to_influx_db(inverter_data, update_date):
        # Write to Influxdb
        if influx.lower() == "true":
            logging.info('InfluxDB output is enabled, posting outputs now...')
            json_body = [
                {
                    "measurement": influx_measurement,
                    "tags": {
                        "deviceId": device_id
                    },
                    "time": int(update_date),
                    "fields": inverter_data
                }
            ]
            if influx_user != "" and influx_password != "":
                client = InfluxDBClient(host=influx_server, port=influx_port, username=influx_user,
                                        password=influx_password)
            else:
                client = InfluxDBClient(host=influx_server, port=influx_port)

            client.switch_database(influx_database)
            success = client.write_points(json_body, time_precision='ms')
            if not success:
                logging.error('Error writing to influx database')

    def write_to_pvoutput(inverter_data, update_date):
        # Write to PVOutput
        if pvoutput.lower() == "true":
            logging.info('PvOutput output is enabled, posting results now...')

            headers = {
                "X-Pvoutput-Apikey": pvoutput_api,
                "X-Pvoutput-SystemId": pvoutput_system,
                "Content-type": "application/x-www-form-urlencoded",
                "Accept": "text/plain"
            }

            # make seconds
            tuple_time = time.localtime(update_date / 1000)
            # Get hour and date
            date = time.strftime("%Y%m%d", tuple_time)
            hour = time.strftime("%H:%M", tuple_time)

            pvoutputdata = {
                "d": date,
                "t": hour,
                "v1": inverter_data['Daily_Generation'] * 1000,
                "v2": inverter_data['AC_Power'],
                "v3": inverter_data['Daily_Energy_Used'] * 1000,
                "v4": inverter_data['Consumption_Power'],
                "v6": inverter_data['AC_Voltage']
            }
            # Python3 change
            encoded = urllib.parse.urlencode(pvoutputdata)

            pvoutput_result = requests.post(
                "http://pvoutput.org/service/r2/addstatus.jsp",
                data=encoded,
                headers=headers
            )
            logging.debug('PvOutput response: %s' % pvoutput_result.content)
            if pvoutput_result.status_code != 200:
                logging.error('Error posting to PvOutput')

    def write_to_mqtt(inverter_data, update_date):
        # Push to MQTT
        if mqtt.lower() == "true":
            logging.info('MQTT output is enabled, posting results now...')

            import paho.mqtt.publish as publish
            msgs = []

            # Create the topic base using the client_id and serial number
            mqtt_topic = ''.join([mqtt_client, "/"])

            if mqtt_username != "" and mqtt_password != "":
                auth_settings = {'username': mqtt_username, 'password': mqtt_password}
            else:
                auth_settings = None

            msgs.append((mqtt_topic + "updateDate", int(update_date), 0, False))
            for key, value in inverter_data.items():
                msgs.append((mqtt_topic + key, value, 0, False))

            publish.multiple(msgs, hostname=mqtt_server, auth=auth_settings)

    if api_key_id == "" or api_key_pw == "":
        logging.error('Key ID and secret are mandatory for Solis Cloud API')
        return

    # download data
    inverter_detail_body = get_inverter_list_body()
    content = get_solis_cloud_data(endpoint_inverter_detail, inverter_detail_body)
    inverter_detail = json.loads(content)["data"]
    timestamp_current = inverter_detail["dataTimestamp"]

    # push to database
    json_formatted_str = json.dumps(inverter_detail, indent=2)
    logging.debug(json_formatted_str)

    # output data
    if influx == "true":
        write_to_influx_db(inverter_detail, timestamp_current)

    if pvoutput == "true":
        write_to_pvoutput(inverter_detail, timestamp_current)

    if mqtt == "true":
        write_to_mqtt(inverter_detail, timestamp_current)


def main():
    """the main method"""

    global NEXT_RUN_YES
    try:
        do_work()
    except Exception as exception:
        logging.error('%s : %s' % (type(exception).__name__, str(exception)))
    NEXT_RUN_YES = 1


global NEXT_RUN_YES

GET_LOGLEVEL = "debug"  # os.environ['LOG_LEVEL']
LOGLEVEL = logging.INFO
if GET_LOGLEVEL.lower() == "info":
    LOGLEVEL = logging.INFO
elif GET_LOGLEVEL.lower() == "error":
    LOGLEVEL = logging.ERROR
elif GET_LOGLEVEL.lower() == "debug":
    LOGLEVEL = logging.DEBUG

logging.basicConfig(level=LOGLEVEL, format='%(asctime)s %(levelname)s %(message)s')
logging.info('Started ginlong-solis-api-connector')

schedule.every(1).minutes.at(':00').do(main).run()
# schedule.every(5).minutes.at(':00').do(main).run()
while True:
    if NEXT_RUN_YES == 1:
        next_run = schedule.next_run().strftime('%d/%m/%Y %H:%M:%S')
        logging.info('Next run is scheduled at %s' % next_run)
        NEXT_RUN_YES = 0
    schedule.run_pending()
    time.sleep(1)
