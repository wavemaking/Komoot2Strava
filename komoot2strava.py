# Based on code provided by:
# https://python.plainenglish.io/get-komoot-tour-data-without-api-143df64e51fa
# https://komoog.readthedocs.io/en/latest/api/komoot.html
# https://github.com/conge/stravaupload

# To get a strava access token with scope activity:write, refer to these sites (particularly the first one)
# https://medium.com/analytics-vidhya/accessing-user-data-via-the-strava-api-using-stravalib-d5bee7fdde17
# https://stackoverflow.com/questions/52880434/problem-with-access-token-in-strava-api-v3-get-all-athlete-activities


import json
import logging
import os
import requests
from dateutil import parser
from stravalib import Client

LOGIN_URL = "https://account.komoot.com/v1/signin"
SIGNIN_URL = "https://account.komoot.com/actions/transfer?type=signin"
TOUR_URL = 'https://www.komoot.com/api/v007/users/1714012209405/tours/?sport_types=&type=tour_recorded&sort_field=date&sort_direction=desc&name=&status=private&hl=nl&page={}&limit=24'
GPX_URL = 'https://www.komoot.com/api/v007/tours/{}.gpx'
LOG_FILE = os.path.expanduser("~/.komoot2strava/komoot2strava.log")
KOMOOT_CRED_FILE = os.path.expanduser("~/.komoot2strava/komoot_account.json")
STRAVE_CRED_FILE = os.path.expanduser("~/.komoot2strava/strava_account.json")
DOWNLOAD_FN = os.path.expanduser("~/.komoot2strava/downloaded/{}_{}.gpx")

with open(KOMOOT_CRED_FILE,'r') as f:
    KOMOOT_CRED = json.load(f)

with open(STRAVE_CRED_FILE,'r') as f:
    STRAVA_CRED = json.load(f)


def logger_config(
        logger=None, log_file=None,
        console_log_level='debug', file_log_level='debug',
        capture_warnings=True,
    ):

    try:  # TODO: Upgrade to log file rotation ?
        os.remove(log_file)
    except BaseException:
        pass

    if logger is not None:
        print('Warning: you specified an existing logger. This is now overwritten.')

    # Do not use a name here as otherwise it will not be considered the root
    # logger (and loggers in imported modules will complain that they cannot
    # find handlers (or you need to resort to dot notation hierarchy).

    logger = logging.getLogger()

    # Remove handlers from a pre-existing session (when running jupyter/interactive)
    while logger.handlers:
        logger.handlers.pop()

    # See https://docs.python.org/2/howto/logging-cookbook.html
    logger.setLevel(logging.DEBUG)

    # create formatter and add it to the handlers
    logger_fmt = '[%(asctime)s] p%(process)s {%(pathname)s:%(lineno)d} %(levelname)s - %(message)s'
    logger_datefmt = '%m-%d %H:%M:%S'

    # create console handler with a higher log level
    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, console_log_level.upper()))
    ch.setFormatter(logging.Formatter(logger_fmt, logger_datefmt, '%'))
    logger.addHandler(ch)

    if log_file is not None:
        # create file handler which logs even debug messages
        fh = logging.FileHandler(log_file)
        fh.setLevel(getattr(logging, file_log_level.upper()))
        fh.setFormatter(logging.Formatter(logger_fmt, logger_datefmt))
        logger.addHandler(fh)

    logging.captureWarnings(capture_warnings)

    return logger

LOGGER = logger_config(
    log_file=LOG_FILE, console_log_level="info", file_log_level="debug"
)    

def komoot_get_session():

    s = requests.Session()

    res = requests.get(LOGIN_URL)
    cookies = res.cookies.get_dict()

    headers = {
        "Content-Type": "application/json"
    }

    payload = json.dumps({
        "email": KOMOOT_CRED["email"],
        "password": KOMOOT_CRED["password"],
        "reason": "null"
    })

    s.post(LOGIN_URL,
        headers=headers,
        data=payload,
        cookies=cookies,
        )

    s.get(SIGNIN_URL)

    return s


def komoot_get_tour_page(s, page):

    headers = {"onlyprops": "true"}

    LOGGER.info(f"Fetching page {page}")
    response = s.get(TOUR_URL.format(page), headers=headers)
    if response.status_code != 200:
        LOGGER.error("Culd not retrieve from Komoot. Something went wrong...")
        raise ValueError
    data = response.json()

    return data


def tour_gpx_fn(tour):

    return DOWNLOAD_FN.format(
        parser.parse(tour["date"]).strftime("%Y_%m_%d %H_%M_%S %z").replace("+", "plus").replace("-","min").replace("_","-"),
        tour["name"]
    )


def download_gpx(s, tour, fn):

    headers = {"onlyprops": "true"}
    response =s.get(GPX_URL.format(tour["id"]), headers=headers)
    gpx_str = response.text
    with open(fn, "w") as fid:
        fid.write(gpx_str)


def strava_get_session():

    s = Client()
    s.access_token = STRAVA_CRED["access_token"]

    return s


def strava_upload(s, fn, name="", activity_type=None):

    LOGGER.info(f'Uploading {fn} to strava...')
    try:        
        upload = s.upload_activity(
            activity_file=open(fn, 'r'),
            data_type="gpx",
            name=name,
            activity_type=activity_type
        )
        activity = upload.wait()
        LOGGER.info('Succeeded uploading activity  - id: ' + str(activity.id))

    except Exception as error:
        LOGGER.error('An exception occurred when uploading to strava: '),
        LOGGER.error(error)


def komoot2strava(break_on_existing=True):

    ks = komoot_get_session()
    ss = strava_get_session()

    page = -1
    while True:
        page += 1
        data = komoot_get_tour_page(ks, page)

        if "_embedded" in data:
            tours = data["_embedded"]["tours"]
            for tour in tours:                
                LOGGER.info(f"Checking tour {tour['name']} - {tour['date']}")
                fn = tour_gpx_fn(tour)
                if os.path.isfile(fn):
                    LOGGER.info("Tour already available on disk.")
                    if break_on_existing:
                        LOGGER.info("Stopping further processing as break_on_existing was set to True")
                        break
                else:
                    LOGGER.info("Tour not available on disk. Downloading...")
                    download_gpx(ks, tour, fn)                    
                    if tour["sport"] == "mtb":
                        activity_type = "MountainBikeRide"
                    elif tour["sport"] == "hike":
                        activity_type = "Hike"
                    else:
                        activity_type = None
                    strava_upload(ss, fn, name=tour["name"], activity_type=activity_type)

        else:
            LOGGER.info("Reached end of komoot pages")
            break


if __name__ == "__main__":

    komoot2strava()
