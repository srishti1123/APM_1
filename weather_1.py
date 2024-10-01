import ddtrace.sourcecode.setuptools_auto
from flask import Flask, request, render_template, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func
import os
import json
import urllib.request
import sys
import logging
from pythonjsonlogger import jsonlogger
from ddtrace import patch; patch(logging=True)
from ddtrace import config
from ddtrace import tracer
from ddtrace.profiling import Profiler
import atexit
profiler = Profiler()
profiler.start()

# Ensure the profiler stops gracefully on exit
atexit.register( profiler.stop)


# Manually set Git metadata environment variables (if not set in the shell)
os.environ['DD_GIT_COMMIT_SHA'] = 'ec58ead5e32ddfd1834e0f30d627ef8909768d6a'
os.environ['DD_GIT_REPOSITORY_URL'] = 'https://github.com/srishti1123/APM_1.git'

config.env = os.getenv('DD_ENV', 'dev')  
config.service = os.getenv('DD_SERVICE', 'python')  
config.version = os.getenv('DD_VERSION', 'v2') 

# no-dd-sa:python-best-practices/init-method-required
class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        # Add trace_id and span_id from Datadog tracing
        log_record['dd.trace_id'] = tracer.current_trace_id()
        log_record['dd.span_id'] = tracer.current_span_id()
        log_record['dd.service'] = config.service
        log_record['dd.env'] = config.env
        log_record['dd.version'] = config.version
        log_record['git.commit.sha'] = os.getenv('DD_GIT_COMMIT_SHA', 'unknown')
        log_record['git.repository_url'] = os.getenv('DD_GIT_REPOSITORY_URL', 'unknown')
logHandler = logging.FileHandler(filename='C:\\Users\\Srishti\\Downloads\\APM_1\\APM_1\\logs.json')
formatter = CustomJsonFormatter()
logHandler.setFormatter(formatter)

FORMAT = ('%(asctime)s %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] '
          '[dd.service=%(dd.service)s dd.env=%(dd.env)s dd.version=%(dd.version)s dd.trace_id=%(dd.trace_id)s dd.span_id=%(dd.span_id)s] '
          '- %(message)s')
logging.basicConfig(format=FORMAT)

logger = logging.getLogger(__name__)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

tracer.set_tags({"track_error":True})

app = Flask(__name__)

# Setting path for database file
basedir = os.path.abspath(os.path.dirname(__file__))

app.config['SQLALCHEMY_DATABASE_URI'] =\
    'sqlite:///' + os.path.join(basedir, 'weather.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Weather(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    country_code = db.Column(db.String(5), nullable=False)
    coordinate = db.Column(db.String(20), nullable=False)
    temp = db.Column(db.String(5))
    pressure = db.Column(db.Integer)
    humidity = db.Column(db.Integer)
    cityname = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True),
                           server_default=func.now())

with app.app_context():
    db.create_all()

# Function to log unhandled exceptions
def except_logging(exc_type, exc_value, exc_traceback):
    logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

# Setting the global exception handler
sys.excepthook = except_logging

def tocelcius(temp):
    logger.debug("Converting temperature to Celsius")
    return str(round(float(temp) - 273.16, 2))

def get_default_city():
    logger.debug("Returning default city")
    return 'Delhi'
    
def save_to_database(weather_details):
    logger.info(f"Saving weather details to database for city {weather_details['cityname']}")
    try:
        weather = Weather(country_code=weather_details["country_code"],
                          coordinate=weather_details["coordinate"],
                          temp=weather_details["temp"],
                          pressure=int(weather_details["pressure"]),
                          humidity=int(weather_details["humidity"]),
                          cityname=weather_details["cityname"])
        db.session.add(weather)
        db.session.commit()
        logger.info("Weather details saved successfully")
    except Exception as e:
        logger.exception("Error saving weather details to database")

def get_weather_details(city):
    api_key = 'bed041794dd5135c931e504ed1cfdf87'
    logger.info(f"Fetching weather details for {city}")
    try:
        source = urllib.request.urlopen(f'http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}').read()
    except Exception as e:
        logger.exception("Error occurred while fetching weather data")
        return abort(400)

    # Converting json data to dictionary
    try:
        list_of_data = json.loads(source)
        logger.debug(f"Weather data fetched: {list_of_data}")
    except json.JSONDecodeError as e:
        logger.exception("Error decoding JSON response")
        return abort(500)

    # Data for variable list_of_data
    data = {
        "country_code": str(list_of_data['sys']['country']),
        "coordinate": str(list_of_data['coord']['lon']) + ' ' + str(list_of_data['coord']['lat']),
        "temp": str(list_of_data['main']['temp']) + 'k',
        "temp_cel": tocelcius(list_of_data['main']['temp']) + 'C',
        "pressure": str(list_of_data['main']['pressure']),
        "humidity": str(list_of_data['main']['humidity']),
        "cityname": str(city),
    }

    save_to_database(data)
    logger.info(f"Weather details for {city}: {data}")
    
    return data

def check_valid_city(cityname):
    logger.info("Validating city: %s", cityname)
    try:
        with open("cities.json", encoding="utf8") as file:
            cities = json.load(file)
            
        if not any(city['name'] == cityname for city in cities):
            logger.error("Validation failed: %s is not a valid city name", cityname)
            return abort(400,description="Invalid city name provided")

        logger.info("City validation successful: %s", cityname)
    except FileNotFoundError:
        logger.exception("cities.json file not found")
        return abort(500,description="Internal Server Error.")
    except json.JSONDecodeError:
        logger.exception("Error decoding cities.json file")
        return abort(500,description="Internal Server Error.")
    except Exception as e:
        logger.exception("Unexpected error during city validation")
        return abort(500,description="Internal Server Error.")

    return True

def check_valid_list(list_):
    logger.info("Validating list_: %s", list_)
    try:
        if not list_ or not list_.strip():
            logger.error("Validation failed: 'list_' cannot be null or empty")
            return abort(400, description="'list_' cannot be null or empty.")
        
        # Additional validation logic can be added here
        logger.info("List_ validation successful: %s", list_)
    except Exception as e:
        logger.exception("Unexpected error during list_ validation")
        return abort(500, description="Internal Server Error.")
    
    return True

@app.route('/', methods=['POST', 'GET'])
def weather():
    try:
        if request.method == 'POST':
            city = request.form['city']
            logger.info(f"Received POST request for city: {city}")
        else:
            city = get_default_city()
            logger.info(f"Default city being used: {city}")
        

        check_valid_city(city)
        data = get_weather_details(city)
        logger.info(f"Rendering weather details for {city}")
        
        return render_template('index.html', data=data)
    except Exception as e:
        logger.exception("Error occurred during request handling")
        return abort(500)
    
@app.route('/add-profile', methods=['POST'])
def add_profile():
    try:
        list_ = request.form.get('list_name')  # This could be None if not provided
        logger.info(f"Received list_name: {list_}")
        
        # Validation
        check_valid_list(list_)
        
        # Proceed with adding profile
        profile = Weather(
            country_code="US",
            coordinate="-122.4194 37.7749",
            temp="290k",
            pressure=1013,
            humidity=80,
            cityname=list_,
        )
        db.session.add(profile)
        db.session.commit()
        logger.info("Profile added successfully")
        return "Profile added successfully!", 200
    except Exception as e:
        logger.exception("Error occurred while adding profile")
        return abort(500)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8126)

# class Foo:
#       def bar(bar):
#         pass
# 123==nan
