import subprocess
import time

CEC_CLIENT = r"C:\Program Files\Pulse-Eight\USB-CEC Adapter\cec-client.exe"

class TVController:
    """Контроллер телевизора"""
    
    def __init__(self):
        self.mac_address = TV_MAC
        self.ip_address = TV_IP
        print(f"📺 TV: MAC={self.mac_address}, IP={self.ip_address}")
    
    def power_on(self):
        """Включить ТВ (двойной WOL для надёжности)"""
        try:
            print("📡 Отправка WOL (первый пакет)...")
            send_magic_packet(self.mac_address)
            
            # Ждём 2 секунды и отправляем второй пакет
            time.sleep(2)
            print("📡 Отправка WOL (второй пакет)...")
            send_magic_packet(self.mac_address)
            
            return True
        except Exception as e:
            print(f"⚠️  Ошибка WOL: {e}")
            return False
    
    def is_tv_on(self):
        try:
            result = subprocess.run(
                ['ping', '-n', '1', self.ip_address],
                capture_output=True, text=True, timeout=2
            )
            return result.returncode == 0
        except:
            return False
    def standby(self):
        """Выключить телевизор (standby)"""
        print("⏻ Выключаю ТВ...")
        return self._run_cec_command("standby 0")
    
    def volume_up(self):
        """Увеличить громкость"""
        return self._run_cec_command("volup")
    
    def volume_down(self):
        """Уменьшить громкость"""
        return self._run_cec_command("voldown")
    
    def list_devices(self):
        """Список устройств CEC"""
        try:
            result = subprocess.run(
                [CEC_CLIENT, '-l'],
                capture_output=True,
                text=True,
                timeout=5
            )
            print(result.stdout)
            return True
        except:
            return False

if __name__ == "__main__":
    tv = TVController()
    
    # Тест
    print("\n📋 Устройства CEC:")
    tv.list_devices()
    
    print("\n⏻ Тест включения ТВ...")
    tv.power_on()
    time.sleep(3)
    
    print("\n⏻ Тест выключения ТВ...")
    tv.standby()