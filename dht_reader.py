import os
import random
import logging

logger = logging.getLogger(__name__)

# Load configuration from environment
# DHT_PIN: Physical pin number or BCM pin number depending on the library.
# On Rock Pi S / Radxa, Rockfruit_DHT uses physical header numbers (e.g. pin 11/13/15).
DHT_PIN = int(os.getenv("DHT_PIN", "4"))
DHT_TYPE = int(os.getenv("DHT_TYPE", "11"))

def read_dht():
    """
    Reads temperature and humidity from DHT sensor.
    Tries multiple libraries. If all fail or are unavailable, returns mock values (when in development).
    Returns (temperature, humidity) or (None, None) if measurement fails.
    """
    # 1. Try Rockfruit_DHT (recommended for Radxa/Rock Pi)
    try:
        import Rockfruit_DHT as rockfruit_dht
        sensor = rockfruit_dht.DHT11 if DHT_TYPE == 11 else rockfruit_dht.DHT22
        # Rockfruit_DHT.read_retry returns (humidity, temperature)
        humidity, temperature = rockfruit_dht.read_retry(sensor, DHT_PIN)
        if temperature is not None and humidity is not None:
            return temperature, humidity
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Failed to read from Rockfruit_DHT: {e}")

    # 2. Try Adafruit_DHT
    try:
        import Adafruit_DHT as adafruit_dht
        sensor = adafruit_dht.DHT11 if DHT_TYPE == 11 else adafruit_dht.DHT22
        humidity, temperature = adafruit_dht.read_retry(sensor, DHT_PIN)
        if temperature is not None and humidity is not None:
            return temperature, humidity
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Failed to read from Adafruit_DHT: {e}")

    # 3. Try dht11 (szazo/DHT11_Python)
    try:
        import dht11
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        instance = dht11.DHT11(pin=DHT_PIN)
        result = instance.read()
        if result.is_valid():
            return result.temperature, result.humidity
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Failed to read from dht11 (szazo): {e}")

    # 4. Try pigpio_dht
    try:
        from pigpio_dht import DHT11, DHT22
        sensor = DHT11(gpio=DHT_PIN) if DHT_TYPE == 11 else DHT22(gpio=DHT_PIN)
        result = sensor.read()
        if result.get('valid'):
            return result['temp_c'], result['humidity']
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Failed to read from pigpio_dht: {e}")

    # Fallback to mock value if running in non-SBC/Windows environment or if libraries are missing
    is_development = os.name == 'nt' or os.getenv("DHT_MOCK", "false").lower() == "true"
    if is_development:
        # Generate mock values
        # Temperature: 18.0 to 28.0, Humidity: 40.0 to 70.0
        mock_temp = random.uniform(18.0, 28.0)
        mock_hum = random.uniform(40.0, 70.0)
        logger.info(f"Using mock DHT data (Dev Mode): Temp={mock_temp:.1f}°C, Hum={mock_hum:.1f}%")
        return mock_temp, mock_hum

    logger.error("No DHT library available or reading failed on Linux environment.")
    return None, None
