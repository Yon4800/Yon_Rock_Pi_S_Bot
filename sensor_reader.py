import os
import random
import logging

logger = logging.getLogger(__name__)

def read_sensors():
    """
    Reads temperature, humidity from AHT20, and temperature, pressure from BMP280.
    Returns (temperature, humidity, pressure) or (None, None, None) if measurement fails.
    """
    temperature = None
    humidity = None
    pressure = None

    # Try importing and reading from AHT20 and BMP280 using Adafruit CircuitPython libraries
    try:
        import board
        import adafruit_ahtx0
        import adafruit_bmp280

        # Initialize I2C
        try:
            i2c = board.I2C()
        except Exception as e:
            logger.warning(f"Failed to initialize I2C board: {e}")
            raise

        # Read AHT20
        aht_temp = None
        aht_hum = None
        try:
            # AHT20 standard address is 0x38
            aht = adafruit_ahtx0.AHTx0(i2c)
            aht_temp = aht.temperature
            aht_hum = aht.relative_humidity
        except Exception as e:
            logger.warning(f"Failed to read from AHT20: {e}")

        # Read BMP280
        bmp_temp = None
        bmp_pres = None
        try:
            # BMP280 default I2C address is 0x77, but some breakout boards use 0x76.
            # Try 0x77, fall back to 0x76.
            try:
                bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=0x77)
            except ValueError:
                bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=0x76)
            bmp_temp = bmp.temperature
            bmp_pres = bmp.pressure
        except Exception as e:
            logger.warning(f"Failed to read from BMP280: {e}")

        # Consolidate values
        # Temperature: Prefer AHT20, fallback to BMP280, or average them if both succeeded
        if aht_temp is not None and bmp_temp is not None:
            # Both are available, average them
            temperature = (aht_temp + bmp_temp) / 2.0
        elif aht_temp is not None:
            temperature = aht_temp
        elif bmp_temp is not None:
            temperature = bmp_temp

        humidity = aht_hum
        pressure = bmp_pres

        if temperature is not None or humidity is not None or pressure is not None:
            return temperature, humidity, pressure

    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Failed to read hardware sensors: {e}")

    # Fallback to mock values if running in non-SBC/Windows environment or if libraries are missing
    is_development = os.name == 'nt' or os.getenv("SENSOR_MOCK", "false").lower() == "true"
    if is_development:
        # Generate mock values
        # Temperature: 18.0 to 28.0, Humidity: 40.0 to 70.0, Pressure: 990.0 to 1020.0 hPa
        mock_temp = random.uniform(18.0, 28.0)
        mock_hum = random.uniform(40.0, 70.0)
        mock_pres = random.uniform(990.0, 1020.0)
        logger.info(f"Using mock sensor data (Dev Mode): Temp={mock_temp:.1f}°C, Hum={mock_hum:.1f}%, Pres={mock_pres:.1f}hPa")
        return mock_temp, mock_hum, mock_pres

    logger.error("No sensor library available or reading failed on Linux environment.")
    return None, None, None
