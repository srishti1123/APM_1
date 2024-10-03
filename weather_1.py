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
from ddtrace.debugging import DynamicInstrumentation

# Enable dynamic instrumentation (optional)
DynamicInstrumentation.enable()

# Initialize the profiler
profiler = Profiler()
profiler.start()

# Ensure the profiler stops gracefully on exit
atexit.register(profiler.stop)

# Manually set Git metadata environment variables (if not set in the shell)
os.environ['DD_GIT_COMMIT_SHA'] = 'ec58ead5e32ddfd1834e0f30d627ef8909768d6a'
os.environ['DD_GIT_REPOSITORY_URL'] = 'https://github.com/srishti1123/APM_1.git'

# Configure Datadog
config.env = os.getenv('DD_ENV', 'dev')  
config.service = os.getenv('DD_SERVICE', 'python')  
config.version = os.getenv('DD_VERSION', 'v2') 

# Custom JSON formatter to include Datadog and Git metadata
class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        current_span = tracer.current_span()
        log_record['dd.trace_id'] = current_span.trace_id if current_span else None
        log_record['dd.span_id'] = current_span.span_id if current_span else None
        log_record['dd.service'] = config.service
        log_record['dd.env'] = config.env
        log_record['dd.version'] = config.version
        log_record['git.commit.sha'] = os.getenv('DD_GIT_COMMIT_SHA', 'unknown')
        log_record['git.repository_url'] = os.getenv('DD_GIT_REPOSITORY_URL', 'unknown')

# Configure Logging
logHandler = logging.FileHandler(filename='C:\\Users\\Srishti\\Downloads\\APM_1\\APM_1\\logs.json')
formatter = CustomJsonFormatter()
logHandler.setFormatter(formatter)

FORMAT = ('%(asctime)s %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] '
          '[dd.service=%(dd.service)s dd.env=%(dd.env)s dd.version=%(dd.version)s '
          'dd.trace_id=%(dd.trace_id)s dd.span_id=%(dd.span_id)s] '
          '- %(message)s')
logging.basicConfig(format=FORMAT)

logger = logging.getLogger(__name__)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

# Set a tracer tag to track errors
tracer.set_tags({"track_error": True})

app = Flask(__name__)

# Setting path for database file
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'weather.db')
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
    created_at = db.Column(db.DateTime(timezone=True), server_default=func.now())

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
        weather = Weather(
            country_code=weather_details["country_code"],
            coordinate=weather_details["coordinate"],
            temp=weather_details["temp"],
            pressure=int(weather_details["pressure"]),
            humidity=int(weather_details["humidity"]),
            cityname=weather_details["cityname"]
        )
        db.session.add(weather)
        db.session.commit()
        logger.info("Weather details saved successfully")
    except Exception as e:
        logger.exception("Error saving weather details to database")

def get_weather_details(city):
    api_key = os.getenv('OPENWEATHER_API_KEY', 'your_default_api_key')  # Securely read API key from env
    logger.info(f"Fetching weather details for {city}")
    try:
        source = urllib.request.urlopen(f'http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}').read()
    except Exception as e:
        logger.exception("Error occurred while fetching weather data")
        return abort(400, description="Bad Request: Unable to fetch weather data.")

    # Converting json data to dictionary
    try:
        list_of_data = json.loads(source)
        logger.debug(f"Weather data fetched: {list_of_data}")
    except json.JSONDecodeError as e:
        logger.exception("Error decoding JSON response")
        return abort(422, description="Unprocessable Entity: Invalid JSON response.")

    # Data for variable list_of_data
    try:
        data = {
            "country_code": str(list_of_data['sys']['country']),
            "coordinate": f"{list_of_data['coord']['lon']} {list_of_data['coord']['lat']}",
            "temp": f"{list_of_data['main']['temp']}k",
            "temp_cel": f"{tocelcius(list_of_data['main']['temp'])}C",
            "pressure": str(list_of_data['main']['pressure']),
            "humidity": str(list_of_data['main']['humidity']),
            "cityname": str(city),
        }
    except KeyError as e:
        logger.exception("Missing key in JSON response: %s", e)
        return abort(400, description="Bad Request: Missing weather data fields.")

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
            return abort(400, description="Invalid city name provided.")

        logger.info("City validation successful: %s", cityname)
    except FileNotFoundError:
        logger.exception("cities.json file not found")
        return abort(404, description="Cities file not found.")
    except json.JSONDecodeError:
        logger.exception("Error decoding cities.json file")
        return abort(422, description="Unprocessable Entity: Invalid cities data format.")
    except Exception as e:
        logger.exception("Unexpected error during city validation")
        return abort(500, description="Internal Server Error.")

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

# Routes to generate different types of errors for testing
@app.route('/error/name', methods=['GET'])
def error_name():
    logger.info("Triggering NameError")
    undefined_variable += 1  # Undefined variable
    return "This will not be returned."

@app.route('/error/type', methods=['GET'])
def error_type():
    logger.info("Triggering TypeError")
    result = 'string' + 5  # Incompatible types
    return "This will not be returned."

@app.route('/error/value', methods=['GET'])
def error_value():
    logger.info("Triggering ValueError")
    int("invalid_integer")  # Invalid conversion
    return "This will not be returned."

@app.route('/error/index', methods=['GET'])
def error_index():
    logger.info("Triggering IndexError")
    my_list = [1, 2, 3]
    return my_list[5]  # Out-of-range index

@app.route('/error/key', methods=['GET'])
def error_key():
    logger.info("Triggering KeyError")
    my_dict = {'a': 1, 'b': 2}
    return my_dict['c']  # Non-existent key

@app.route('/error/attribute', methods=['GET'])
def error_attribute():
    logger.info("Triggering AttributeError")
    my_list = [1, 2, 3]
    return my_list.non_existent_method()  # Undefined attribute

@app.route('/error/division', methods=['GET'])
def error_division():
    logger.info("Triggering ZeroDivisionError")
    return 1 / 0  # Division by zero

# Custom Exception
class CustomException(Exception):
    pass

@app.route('/error/custom', methods=['GET'])
def error_custom():
    logger.info("Triggering CustomException")
    raise CustomException("This is a custom exception for testing purposes.")

# Existing weather route
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
        return abort(500, description="Internal Server Error.")

@app.route('/add-profile', methods=['POST'])
def add_profile():
    try:
        list_ = request.form.get('list_name')  # This could be None if not provided
        logger.info(f"Received list_name: {list_}")

        # Validation
        check_valid_list(list_)

        # Induce specific errors based on input
        if list_ == "value_error":
            raise ValueError("Induced ValueError for testing.")
        elif list_ == "type_error":
            raise TypeError("Induced TypeError for testing.")
        elif list_ == "custom_error":
            raise CustomException("Induced CustomException for testing.")

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
    except ValueError as ve:
        logger.exception("ValueError occurred while adding profile")
        return abort(400, description=str(ve))
    except TypeError as te:
        logger.exception("TypeError occurred while adding profile")
        return abort(400, description=str(te))
    except CustomException as ce:
        logger.exception("CustomException occurred while adding profile")
        return abort(400, description=str(ce))
    except Exception as e:
        logger.exception("Error occurred while adding profile")
        return abort(500, description="Internal Server Error.")

# Custom error handlers for specific exception types
@app.errorhandler(NameError)
def handle_name_error(e):
    logger.exception("Handled NameError")
    return {"error": "NameError: Undefined variable."}, 400

@app.errorhandler(TypeError)
def handle_type_error(e):
    logger.exception("Handled TypeError")
    return {"error": "TypeError: Incompatible types used."}, 400

@app.errorhandler(ValueError)
def handle_value_error(e):
    logger.exception("Handled ValueError")
    return {"error": "ValueError: Invalid value provided."}, 400

@app.errorhandler(KeyError)
def handle_key_error(e):
    logger.exception("Handled KeyError")
    return {"error": "KeyError: Missing key in data."}, 400

@app.errorhandler(AttributeError)
def handle_attribute_error(e):
    logger.exception("Handled AttributeError")
    return {"error": "AttributeError: Undefined attribute accessed."}, 400

@app.errorhandler(ZeroDivisionError)
def handle_zero_division_error(e):
    logger.exception("Handled ZeroDivisionError")
    return {"error": "ZeroDivisionError: Division by zero."}, 400

@app.errorhandler(CustomException)
def handle_custom_exception(e):
    logger.exception("Handled CustomException")
    return {"error": f"CustomException: {str(e)}"}, 400

@app.errorhandler(404)
def handle_not_found_error(e):
    logger.exception("Handled 404 Not Found")
    return {"error": "404 Not Found: The requested resource was not found."}, 404

@app.errorhandler(422)
def handle_unprocessable_entity_error(e):
    logger.exception("Handled 422 Unprocessable Entity")
    return {"error": "422 Unprocessable Entity: The request was well-formed but unable to be followed."}, 422

@app.errorhandler(500)
def handle_internal_server_error(e):
    logger.exception("Handled 500 Internal Server Error")
    return {"error": "500 Internal Server Error: An unexpected error occurred."}, 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8126)
