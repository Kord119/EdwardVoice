import json
import queue
import sounddevice as sd
import numpy as np
from vosk import Model, KaldiRecognizer
import asyncio
import edge_tts
import os
import sys
import tempfile
import time
import subprocess
from wakeonlan import send_magic_packet
from collections import deque
import re

from llm_controller import LLMController
from starline_controller import StarLineController

# === НАСТРОЙКИ ===
MODEL_PATH = "vosk-model-small-ru-0.22"
VLC_PATH = r"C:\Program Files\VideoLAN\VLC\vlc.exe"
TTS_VOICE = "ru-RU-DmitryNeural"

# === НАСТРОЙКИ TV ===
TV_MAC = "E4:8A:93:F2:4E:79"  # ← ЗАМЕНИТЕ НА ВАШ MAC
TV_IP = "192.168.1.100"       # ← ЗАМЕНИТЕ НА ВАШ IP


class TVController:
    """Контроллер телевизора"""
    
    def __init__(self):
        self.mac_address = TV_MAC
        self.ip_address = TV_IP
        print(f"📺 TV: MAC={self.mac_address}, IP={self.ip_address}")
    
    def power_on(self):
        try:
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


class AudioBuffer:
    """Кольцевой буфер аудио"""
    
    def __init__(self, duration_seconds=3.0, sample_rate=16000):
        self.sample_rate = sample_rate
        self.max_samples = int(duration_seconds * sample_rate)
        self.buffer = deque(maxlen=self.max_samples)
    
    def add(self, audio_bytes):
        samples = np.frombuffer(audio_bytes, dtype=np.int16)
        self.buffer.extend(samples)
    
    def get_audio(self, duration_seconds=None):
        if duration_seconds:
            samples = int(duration_seconds * self.sample_rate)
            data = list(self.buffer)[-samples:]
        else:
            data = list(self.buffer)
        return np.array(data, dtype=np.int16)


class EdwardAgent:
    def __init__(self, model_path=MODEL_PATH):
        if not os.path.exists(model_path):
            print(f"❌ Модель не найдена: {model_path}")
            sys.exit(1)
        
        print("📥 Загрузка модели Vosk...")
        self.model = Model(model_path)
        self.recognizer = KaldiRecognizer(self.model, 16000)
        
        self.audio_buffer = AudioBuffer(duration_seconds=3.0)
        self.q = queue.Queue()
        
        self.tv_controller = TVController()
        self.llm = LLMController(model_name="qwen2.5:7b")
        self.llm_activated = False
        self.starline = StarLineController()
        
 #       self.llm.preload()
        
        if os.path.exists(VLC_PATH):
            print("✅ VLC найден")
        else:
            print("⚠️  VLC не найден")
        
        print("🚗 StarLine готов")
    
    def callback(self, indata, frames, time, status):
        if status:
            print(status, file=sys.stderr)
        self.q.put(bytes(indata))
    
    def check_wake_word(self, text):
        """
        Проверяет wake-word и возвращает остаток команды.
        
        Returns:
            tuple: (is_wake_word, remaining_command)
            - Если "привет эдвард включи свет" → (True, "включи свет")
            - Если просто "привет эдвард" → (True, "")
            - Если нет wake-word → (False, text)
        """
        text_lower = text.lower().strip()
        
        # Паттерны wake-word
        wake_patterns = [
            "привет эдвард",
            "привет edward",
            "privet edward",
            "эдвард",
        ]
        
        for pattern in wake_patterns:
            if pattern in text_lower:
                # Извлекаем команду (всё после wake-word)
                start_pos = text_lower.find(pattern) + len(pattern)
                remaining = text[start_pos:].strip()
                
                # Убираем возможные запятые/паузы в начале
                remaining = remaining.lstrip(' ,.:;-')
                
                return True, remaining
        
        return False, text
    
    def play_beep(self, freq=880, duration=0.05):
        t = np.linspace(0, duration, int(48000 * duration))
        envelope = np.exp(-5 * t / duration)
        beep = (np.sin(2 * np.pi * freq * t) * envelope * 0.2).astype(np.float32)
        sd.play(beep, samplerate=48000)
        sd.wait()
    
    async def speak(self, text):
        """Озвучивание с перебором мужских голосов"""
        if not text:
            return
        
        # Очистка текста
        text = text.replace('**', '').replace('*', '')
        text = text.replace('`', '').replace('#', '').replace('```', '')
        
        emoji_pattern = re.compile("["
            u"\U0001F600-\U0001F64F"
            u"\U0001F300-\U0001F5FF"
            u"\U0001F680-\U0001F6FF"
            u"\U0001F1E0-\U0001F1FF"
            u"\U00002702-\U000027B0"
            u"\U000024C2-\U0001F251"
            "]+", flags=re.UNICODE)
        text = emoji_pattern.sub('', text)
        text = ' '.join(text.split())
        
        if len(text) > 500:
            sentences = re.split(r'[.!?]+', text)
            sentences = [s.strip() for s in sentences if s.strip()]
            text = '. '.join(sentences[:3]) + '.'
        
        if len(text.strip()) < 3:
            return
        
        print(f"🔊 {text}")
        
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
            tmp_path = tmp.name
        
        try:
            # Все доступные МУЖСКИЕ русские голоса
            male_voices = [
                "ru-RU-DmitryNeural",    # Основной мужской
                "ru-RU-PavelNeural",     # Альтернативный мужской (если есть)
                "ru-RU-SvetlanaNeural",  # Женский (последний fallback)
            ]
            
            for voice in male_voices:
                try:
                    print(f"🎤 Пробую {voice}...")
                    communicate = edge_tts.Communicate(text, voice)
                    await communicate.save(tmp_path)
                    
                    if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                        raise Exception("Файл не создан")
                    
                    print(f"✅ {voice} сработал!")
                    
                    # Воспроизведение
                    if os.path.exists(VLC_PATH):
                        subprocess.run([
                            VLC_PATH, '--intf=dummy', '--play-and-exit',
                            '--no-video', '--qt-start-minimized', tmp_path
                        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        os.startfile(tmp_path)
                    
                    await asyncio.sleep(0.3)
                    return  # Успех!
                    
                except Exception as voice_err:
                    print(f"⚠️  {voice} не сработал: {voice_err}")
                    continue
            
            print("❌ Ни один голос не сработал")
            
        except Exception as e:
            print(f"❌ Критическая ошибка: {e}")
        
        finally:
            await asyncio.sleep(0.5)
            try:
                os.unlink(tmp_path)
            except:
                pass
    
    async def _ask_llm_activation(self):
        """Спросить пользователя об активации LLM"""
        print("❓ Запрашиваю разрешение на активацию LLM...")
        
        # Озвучиваем вопрос
        await self.speak("Для ответа на этот вопрос нужна нейросеть. Активировать LLM?")
        
        # Слушаем ответ
        print("🎙️  Слушаю ответ (да/нет)...")
        answer = await self._listen_yes_no()
        
        if answer == "yes":
            print("✅ Пользователь подтвердил активацию LLM")
            await self.speak("Активирую нейросеть, это займёт несколько секунд.")
            
            # Активируем LLM
            success = await asyncio.to_thread(self.llm.preload)
            
            if success:
                self.llm_activated = True
                await self.speak("Нейросеть готова. Задавайте вопросы.")
                return True
            else:
                await self.speak("Не удалось активировать нейросеть.")
                return False
        
        elif answer == "no":
            print("❌ Пользователь отказался от активации LLM")
            return False
        
        else:
            print("⚠️  Не распознан ответ")
            await self.speak("Не поняла ответ. Повторите позже.")
            return False
    
    async def _listen_yes_no(self, timeout=3.0):
        """Слушать короткий ответ да/нет"""
        self.play_beep(880, duration=0.05)
        
        yes_no_recognizer = KaldiRecognizer(self.model, 16000)
        
        start_time = asyncio.get_event_loop().time()
        silence_count = 0
        max_silence = 8
        has_speech = False
        
        while True:
            try:
                data = self.q.get(timeout=0.1)
                
                audio_chunk = np.frombuffer(data, dtype=np.int16)
                rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))
                
                if rms > 500:
                    has_speech = True
                    silence_count = 0
                else:
                    if has_speech:
                        silence_count += 1
                
                if yes_no_recognizer.AcceptWaveform(data):
                    result = json.loads(yes_no_recognizer.Result())
                    text = result.get("text", "").strip().lower()
                    
                    if text:
                        print(f"💬 Ответ: '{text}'")
                        self.play_beep(1320, duration=0.05)
                        
                        # Определяем да/нет
                        if any(word in text for word in ["да", "ага", "конечно", "yes", "activate", "активируй"]):
                            return "yes"
                        elif any(word in text for word in ["нет", "не", "no", "не надо", "отмена"]):
                            return "no"
                
                if silence_count > max_silence and has_speech:
                    break
                
                if asyncio.get_event_loop().time() - start_time > timeout:
                    break
                    
            except queue.Empty:
                continue
        
        # Финальный результат
        result = json.loads(yes_no_recognizer.FinalResult())
        text = result.get("text", "").strip().lower()
        
        if text:
            print(f"💬 Ответ (финальный): '{text}'")
            if any(word in text for word in ["да", "ага", "конечно", "yes"]):
                return "yes"
            elif any(word in text for word in ["нет", "не", "no"]):
                return "no"
        
        return "unknown"
    async def listen_command_fast(self, timeout=4.0):
        """Быстрое прослушивание команды"""
        print("🎙️  Слушаю...")
        self.play_beep(880, duration=0.05)
        
        cmd_recognizer = KaldiRecognizer(self.model, 16000)
        
        buffered_audio = self.audio_buffer.get_audio(duration_seconds=2.0)
        if len(buffered_audio) > 0:
            buffered_bytes = buffered_audio.tobytes()
            cmd_recognizer.AcceptWaveform(buffered_bytes)
        
        start_time = asyncio.get_event_loop().time()
        silence_count = 0
        max_silence = 10
        has_speech = False
        
        while True:
            try:
                data = self.q.get(timeout=0.1)
                
                audio_chunk = np.frombuffer(data, dtype=np.int16)
                rms = np.sqrt(np.mean(audio_chunk.astype(np.float32) ** 2))
                
                if rms > 500:
                    has_speech = True
                    silence_count = 0
                else:
                    if has_speech:
                        silence_count += 1
                
                if cmd_recognizer.AcceptWaveform(data):
                    result = json.loads(cmd_recognizer.Result())
                    text = result.get("text", "").strip()
                    
                    if text and not self.check_wake_word(text):
                        print(f"💬 '{text}'")
                        self.play_beep(1320, duration=0.05)
                        return text
                
                if silence_count > max_silence and has_speech:
                    break
                
                if asyncio.get_event_loop().time() - start_time > timeout:
                    break
                    
            except queue.Empty:
                continue
        
        result = json.loads(cmd_recognizer.FinalResult())
        text = result.get("text", "").strip()
        if text and not self.check_wake_word(text):
            print(f"💬 '{text}'")
            return text
        return None
    
    async def process_command(self, text):
        """Обработка команды"""
        text_lower = text.lower().strip()
        
        # === КОМАНДЫ ЗАВЕРШЕНИЯ ===
        if text_lower in ["выход", "выйди", "стоп", "хватит", "отключись", "выключись", "пока", "до свидания"]:
            return "До свидания! Буду ждать вас снова."
        
        # === КОМАНДЫ ДЛЯ ТЕЛЕВИЗОРА ===
        elif "включи телевизор" in text_lower or "включи тв" in text_lower:
            if self.tv_controller.power_on():
                return "Включаю телевизор."
            return "Не удалось включить."
        
        elif "телевизор включен" in text_lower or "тв включен" in text_lower:
            return "Да, включен." if self.tv_controller.is_tv_on() else "Выключен."
        
        # === КОМАНДЫ ДЛЯ МАШИНЫ ===

        # Открытие/снятие с охраны - ДОБАВЬТЕ ЭТОТ БЛОК ПЕРЕД другими командами машины!
        elif any(word in text_lower for word in [
            "открой", "открыва", "сними", "снимай", "разблокир"
        ]) and any(word in text_lower for word in [
            "машин", "авто", "двер", "охран", "сигнализ"
        ]):
            print("🔓 Открытие машины...")
            response = await self.starline.unlock_doors()
            return response

        # Закрытие/постановка на охрану
        elif any(word in text_lower for word in [
            "закрой", "закрыва", "поставь", "ставь", "блокир"
        ]) and any(word in text_lower for word in [
            "машин", "авто", "двер", "охран", "сигнализ"
        ]):
            print("🔒 Закрытие машины...")
            response = await self.starline.lock_doors()
            return response

        # Запуск двигателя
        elif any(word in text_lower for word in ["заведи", "запусти", "старт"]) and \
             any(word in text_lower for word in ["машин", "авто", "двигател", "мотор"]):
            print("🚗 Запуск машины...")
            response = await self.starline.start_engine()
            return response

        # Остановка двигателя
        elif any(word in text_lower for word in ["заглуши", "останови", "выключи"]) and \
             any(word in text_lower for word in ["машин", "авто", "двигател", "мотор"]):
            print("🛑 Остановка машины...")
            response = await self.starline.stop_engine()
            return response

        # Статус машины
        elif any(word in text_lower for word in [
            "статус", "состояни", "состоян", "состоянь", 
            "что с", "как там", "как дела"
        ]) and any(word in text_lower for word in ["машин", "авто", "тачк"]):
            print("📊 Проверка статуса машины...")
            response = await self.starline.get_status()
            return response
                
        # === БЫСТРЫЕ КОМАНДЫ ===
        elif "время" in text_lower or "час" in text_lower:
            return f"Сейчас {time.strftime('%H:%M')}"
        
        elif "дата" in text_lower or "число" in text_lower:
            return f"Сегодня {time.strftime('%d %B %Y')}"
        
        elif "очисти память" in text_lower or "забудь всё" in text_lower:
            self.llm.clear_history()
            return "Память очищена."
        
        elif "что ты умеешь" in text_lower:
            return ("Я могу управлять телевизором и машиной через StarLine, "
                    "говорить время и дату, отвечать на вопросы и поддерживать беседу.")
        
        # === ФИЛЬТР ===
        elif len(text_lower) < 4:
            return "Не расслышал, повторите, пожалуйста."
            
        # === КОМАНДА АКТИВАЦИИ LLM ===
        elif "активируй ллм" in text_lower or "включи нейросеть" in text_lower or "включи ллм" in text_lower:
            if self.llm_activated:
                return "Нейросеть уже активна."
            
            activated = await self._ask_llm_activation()
            if activated:
                return "Нейросеть активирована и готова к работе."
            else:
                return "Активация отменена."
        
        elif "отключи llm" in text_lower or "выключи нейросеть" in text_lower:
            if self.llm_activated:
                self.llm_activated = False
                self.llm.clear_history()
                return "Нейросеть отключена. Для следующего вопроса спрошу разрешение снова."
            return "Нейросеть уже отключена."
            
        # === ВСЁ ОСТАЛЬНОЕ → LLM ===
        else:
            print("🧠 Думаю...")
            
            # Проверяем активирован ли LLM
            if not self.llm_activated:
                # Запрашиваем разрешение
                activated = await self._ask_llm_activation()
                
                if not activated:
                    # LLM не активирован - не можем ответить
                    return "Для ответа на этот вопрос нужно активировать нейросеть. Скажите 'активируй llm' чтобы включить."
            
            # LLM активирован - задаём вопрос
            answer = await self.llm.ask(text)
            return answer
    
    async def run(self):
        print("\n" + "=" * 70)
        print("🎤 EDWARD - ГОЛОСОВОЙ АССИСТЕНТ + LLM + STARLINE")
        print("=" * 70)
        print("Скажите: 'Привет Эдвард' + сразу команду")
        print("\n🚗 Команды для машины:")
        print("  • 'Привет Эдвард заведи машину'")
        print("  • 'Привет Эдвард статус машины'")
        print("  • 'Привет Эдвард сними с охраны авто'")
        print("=" * 70 + "\n")
        
        try:
            with sd.RawInputStream(
                samplerate=16000,
                blocksize=4000,
                dtype='int16',
                channels=1,
                callback=self.callback
            ):
                print("👂 Слушаю wake-word...\n")
                
                while True:
                    try:
                        data = self.q.get(timeout=0.1)
                        self.audio_buffer.add(data)
                        
                        if self.recognizer.AcceptWaveform(data):
                            result = json.loads(self.recognizer.Result())
                            text = result.get("text", "").strip()
                            
                            if text:
                                # ПРОВЕРЯЕМ wake-word И извлекаем команду!
                                is_wake, remaining_command = self.check_wake_word(text)
                                
                                if is_wake:
                                    print(f"\n✨ Активация: '{text}'")
                                    
                                    # === КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ ===
                                    # Если команда уже была сказана в wake-word фразе
                                    if remaining_command:
                                        print(f"💬 Команда уже сказана: '{remaining_command}'")
                                        self.play_beep(1320, duration=0.05)
                                        
                                        # Сразу обрабатываем эту команду
                                        response = await self.process_command(remaining_command)
                                        await self.speak(response)
                                        print("👂 Жду...\n")
                                        self.recognizer.Reset()
                                    
                                    # Если wake-word был один - слушаем НОВУЮ команду
                                    else:
                                        print("🎙️  Жду команду...")
                                        command = await self.listen_command_fast()
                                        
                                        if command:
                                            response = await self.process_command(command)
                                            await self.speak(response)
                                            print("👂 Жду...\n")
                                            self.recognizer.Reset()
                        
                    except queue.Empty:
                        continue
        
        except KeyboardInterrupt:
            print("\n👋 Выключен")


if __name__ == "__main__":
    agent = EdwardAgent()
    asyncio.run(agent.run())