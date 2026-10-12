import asyncio
import os
import hashlib
import requests
from functools import partial
from dotenv import load_dotenv

load_dotenv()


class StarLineController:
    """
    Контроллер сигнализации StarLine через официальный API
    
    Возможности:
    - Запуск/остановка двигателя
    - Проверка состояния (двигатель, двери, температура)
    - Получение полной информации о машине
    """
    
    SLID_BASE = "https://id.starline.ru"
    WEBAPI_BASE = "https://developer.starline.ru"
    
    def __init__(self):
        self.app_id = os.getenv("STARLINE_APP_ID")
        self.app_secret = os.getenv("STARLINE_APP_SECRET")
        self.username = os.getenv("STARLINE_USERNAME")
        self.password = os.getenv("STARLINE_PASSWORD")
        
        self.session = requests.Session()
        
        self.slnet_token = None
        self.user_id = None
        self.device_id = None
        self.device_name = None
        self.device_data = None  # Кэш данных устройства
        
        print(f"🚗 StarLine контроллер инициализирован")
    
    def _get_app_code(self):
        url = f"{self.SLID_BASE}/apiV3/application/getCode/"
        payload = {
            'appId': self.app_id,
            'secret': hashlib.md5(self.app_secret.encode('utf-8')).hexdigest()
        }
        r = self.session.get(url, params=payload, timeout=10)
        response = r.json()
        if int(response.get('state', 0)) == 1:
            return response['desc']['code']
        raise Exception(f"Ошибка app_code: {response}")
    
    def _get_app_token(self, app_code):
        url = f"{self.SLID_BASE}/apiV3/application/getToken/"
        payload = {
            'appId': self.app_id,
            'secret': hashlib.md5((self.app_secret + app_code).encode('utf-8')).hexdigest()
        }
        r = self.session.get(url, params=payload, timeout=10)
        response = r.json()
        if int(response.get('state', 0)) == 1:
            return response['desc']['token']
        raise Exception(f"Ошибка app_token: {response}")
    
    def _get_slid_user_token(self, app_token):
        try:
            ip_response = requests.get('https://api.ipify.org?format=json', timeout=5)
            user_ip = ip_response.json().get('ip', '')
        except:
            user_ip = ''
        
        url = f"{self.SLID_BASE}/apiV3/user/login/"
        payload = {'token': app_token}
        if user_ip:
            payload['user_ip'] = user_ip
        
        data = {
            'login': self.username,
            'pass': hashlib.sha1(self.password.encode('utf-8')).hexdigest()
        }
        
        r = self.session.post(url, params=payload, data=data, timeout=10)
        response = r.json()
        if int(response.get('state', 0)) == 1:
            return response['desc']['user_token']
        raise Exception(f"Ошибка авторизации: {response}")
    
    def _get_slnet_token_and_user_id(self, slid_token):
        url = f"{self.WEBAPI_BASE}/json/v2/auth.slid"
        data = {'slid_token': slid_token}
        r = self.session.post(url, json=data, timeout=10)
        response = r.json()
        
        if 'slnet' not in r.cookies:
            raise Exception("slnet не найден в cookies")
        if 'user_id' not in response:
            raise Exception("user_id не найден в ответе")
        
        return r.cookies['slnet'], response['user_id']
    
    def _get_device_id(self):
        """Получить device_id из списка устройств"""
        endpoints = [
            f"{self.WEBAPI_BASE}/json/v2/user/{self.user_id}/user_info",
            f"{self.WEBAPI_BASE}/json/v3/user/{self.user_id}/data",
        ]
        
        for url in endpoints:
            try:
                r = self.session.get(url, timeout=10)
                if r.status_code == 200:
                    response = r.json()
                    
                    devices = None
                    if isinstance(response, dict):
                        if 'user_devices' in response:
                            devices = response['user_devices']
                        elif 'devices' in response:
                            devices = response['devices']
                    
                    if devices and len(devices) > 0:
                        return devices[0]
            except:
                continue
        
        raise Exception("Устройства не найдены")
    
    def _authenticate_sync(self):
        """Синхронная авторизация"""
        app_code = self._get_app_code()
        app_token = self._get_app_token(app_code)
        slid_token = self._get_slid_user_token(app_token)
        self.slnet_token, self.user_id = self._get_slnet_token_and_user_id(slid_token)
        
        device = self._get_device_id()
        self.device_id = device.get('device_id') or device.get('deviceId')
        self.device_name = device.get('name') or device.get('device_name') or 'Автомобиль'
        
        return True
    
    async def authenticate(self):
        """Асинхронная авторизация"""
        if not all([self.app_id, self.app_secret, self.username, self.password]):
            return False
        
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._authenticate_sync)
        except Exception as e:
            print(f"⚠️  Ошибка авторизации StarLine: {e}")
            return False
    
    def _get_device_data_sync(self):
        """Синхронное получение данных устройства"""
        url = f"{self.WEBAPI_BASE}/json/v3/device/{self.device_id}/data"
        r = self.session.get(url, timeout=10)
        if r.status_code == 200:
            self.device_data = r.json()
            return self.device_data
        raise Exception(f"Ошибка получения данных: {r.status_code}")
    
    async def get_device_data(self):
        """Получить полные данные об устройстве"""
        if not self.slnet_token:
            if not await self.authenticate():
                return None
        
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._get_device_data_sync)
        except Exception as e:
            print(f"⚠️  Ошибка получения данных: {e}")
            return None
    
    async def get_status(self):
        """Получить краткий статус машины для голосового ответа"""
        data = await self.get_device_data()
        if not data:
            return "Не удалось получить данные о машине."
        
        try:
            # Извлекаем основные параметры
            ct = data.get('ct', {})
            car_state = data.get('car_state', {})
            ct_ext = data.get('ct_ext', {})
            
            # Двигатель
            engine_on = ct.get('engine_on', False) or car_state.get('engine_on', False)
            engine_status = "работает" if engine_on else "выключен"
            
            # Двери
            doors_locked = ct.get('doors_locked', True) or car_state.get('doors_locked', True)
            doors_status = "закрыта" if doors_locked else "открыта"
            
            # Температура
            temp_ext = ct_ext.get('temp_ext') or ct.get('temp_ext')
            temp_engine = ct_ext.get('temp_engine') or ct.get('temp_engine')
            
            # Формируем ответ
            response_parts = []
            response_parts.append(f"Двигатель {engine_status}")
            
            if temp_ext is not None:
                response_parts.append(f"на улице {temp_ext} градусов")
            
            if temp_engine is not None and engine_on:
                response_parts.append(f"двигатель прогрет до {temp_engine} градусов")
            
            response_parts.append(f"машина {doors_status}")
            
            return ". ".join(response_parts) + "."
            
        except Exception as e:
            print(f"⚠️  Ошибка парсинга статуса: {e}")
            return "Не удалось прочитать данные о машине."
    
    async def get_detailed_status(self):
        """Получить детальную информацию о машине"""
        data = await self.get_device_data()
        if not data:
            return "Не удалось получить данные о машине."
        
        try:
            ct = data.get('ct', {})
            car_state = data.get('car_state', {})
            ct_ext = data.get('ct_ext', {})
            
            info = []
            info.append(f"🚗 {self.device_name}")
            
            # Двигатель
            engine_on = ct.get('engine_on', False) or car_state.get('engine_on', False)
            info.append(f"⚙️  Двигатель: {'работает' if engine_on else 'выключен'}")
            
            # Охрана
            alarm = ct.get('alarm', False) or car_state.get('alarm', False)
            info.append(f"🔒 Охрана: {'включена' if alarm else 'выключена'}")
            
            # Двери
            doors_locked = ct.get('doors_locked', True)
            info.append(f"🚪 Двери: {'закрыты' if doors_locked else 'открыты'}")
            
            # Температура
            temp_ext = ct_ext.get('temp_ext') or ct.get('temp_ext')
            if temp_ext is not None:
                info.append(f"🌡️ Температура на улице: {temp_ext}°C")
            
            temp_engine = ct_ext.get('temp_engine') or ct.get('temp_engine')
            if temp_engine is not None:
                info.append(f"🔥 Температура двигателя: {temp_engine}°C")
            
            # Топливо
            fuel = car_state.get('fuel_level') or ct.get('fuel_level')
            if fuel is not None:
                info.append(f"⛽ Топливо: {fuel}%")
            
            # Пробег
            mileage = car_state.get('mileage') or ct.get('mileage')
            if mileage is not None:
                info.append(f"🛣️ Пробег: {mileage} км")
            
            return "\n".join(info)
            
        except Exception as e:
            return f"Ошибка получения данных: {e}"
    
    def _send_command_sync(self, command_type, value):
        """Отправка команды"""
        url = f"{self.WEBAPI_BASE}/json/v2/device/{self.device_id}/async"
        data = {'type': command_type, 'value': value}
        r = self.session.post(url, json=data, timeout=10)
        return r.status_code == 200
    
    async def start_engine(self):
        """Запуск двигателя"""
        if not self.slnet_token:
            if not await self.authenticate():
                return "Не удалось подключиться к StarLine."
        
        try:
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None, 
                partial(self._send_command_sync, 'ign', 1)
            )
            if success:
                return "Запускаю двигатель. Машина прогреется через несколько минут."
            return "Не удалось запустить двигатель."
        except Exception as e:
            return f"Ошибка при запуске: {e}"
    
    async def stop_engine(self):
        """Остановка двигателя"""
        if not self.slnet_token:
            if not await self.authenticate():
                return "Не удалось подключиться к StarLine."
        
        try:
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None,
                partial(self._send_command_sync, 'ign', 0)
            )
            if success:
                return "Останавливаю двигатель."
            return "Не удалось остановить двигатель."
        except Exception as e:
            return f"Ошибка при остановке: {e}"
    
    async def lock_doors(self):
        """Закрыть двери"""
        if not self.slnet_token:
            if not await self.authenticate():
                return "Не удалось подключиться к StarLine."
        
        try:
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None,
                partial(self._send_command_sync, 'lock', 1)
            )
            if success:
                return "Закрываю двери и ставлю на охрану."
            return "Не удалось закрыть двери."
        except Exception as e:
            return f"Ошибка: {e}"
    
    async def unlock_doors(self):
        """Открыть двери"""
        if not self.slnet_token:
            if not await self.authenticate():
                return "Не удалось подключиться к StarLine."
        
        try:
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None,
                partial(self._send_command_sync, 'lock', 0)
            )
            if success:
                return "Открываю двери."
            return "Не удалось открыть двери."
        except Exception as e:
            return f"Ошибка: {e}"