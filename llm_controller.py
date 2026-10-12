import ollama
import asyncio
import re


class LLMController:
    """Контроллер LLM через Ollama"""
    
    def __init__(self, model_name="qwen2.5:7b"):
        self.model_name = model_name
        self.system_prompt = (
            "Ты — Эдвард, умный голосовой ассистент. "
            "Отвечай кратко (2-3 предложения) на русском языке. "
            "Будь дружелюбным. Не используй markdown. "
            "Отвечай сразу, без размышлений."
        )
        
        self.conversation_history = []
        self.max_history = 8
    
    def _add_to_history(self, role: str, content: str):
        self.conversation_history.append({"role": role, "content": content})
        if len(self.conversation_history) > self.max_history * 2:
            self.conversation_history = self.conversation_history[-self.max_history * 2:]
    
    def _enhance_question(self, question: str) -> str:
        """Превратить короткие фразы в вопросы"""
        q = question.strip()
        if len(q) <= 5 and '?' not in q:
            return f"Расскажи кратко про: {q}"
        return q
    
    def _remove_think_tags(self, text: str) -> str:
        """Удаление  тегов"""
        # Метод 1: через regex (надёжный)
        text = re.sub(r'', '', text, flags=re.DOTALL)
        
        # Метод 2: если остались одиночные теги
        text = text.replace('', '')
        text = text.replace('', '')
        
        return text
    
    def _clean_answer(self, text: str) -> str:
        """Очистка ответа с отладкой"""
        original = text
        
        # 🔍 Отладка: что получили
        print(f"🔍 [clean] Вход: {len(text)} симв.")
        
        # Удаляем think-теги
        text = self._remove_think_tags(text)
        print(f"🔍 [clean] После удаления think: {len(text)} симв.")
        
        # Удаляем markdown
        text = text.replace('**', '').replace('*', '')
        text = text.replace('`', '').replace('#', '')
        
        # Убираем лишние пробелы и переносы
        text = ' '.join(text.split())
        print(f"🔍 [clean] После очистки пробелов: {len(text)} симв.")
        
        # Обрезаем длинные ответы
        if len(text) > 400:
            sentences = re.split(r'[.!?]+', text)
            sentences = [s.strip() for s in sentences if s.strip()]
            if sentences:
                text = '. '.join(sentences[:3]) + '.'
            print(f"🔍 [clean] После обрезки: {len(text)} симв.")
        
        # Финальная очистка
        text = text.strip()
        print(f"🔍 [clean] ИТОГО: '{text[:100]}...' (длина {len(text)})")
        
        return text
    
    def preload(self):
        """Предзагрузка модели"""
        try:
            print(f"🧠 Предзагрузка {self.model_name}...")
            ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": "Привет"}],
                keep_alive="24h"
            )
            print("✅ LLM готова")
            return True
        except Exception as e:
            print(f"⚠️  Ошибка: {e}")
            return False
    
    async def ask(self, question: str) -> str:
        """Задать вопрос LLM"""
        try:
            if not question or len(question.strip()) < 2:
                return "Не понял вопрос. Повторите."
            
            enhanced = self._enhance_question(question)
            print(f"📤 Вопрос: {question} → {enhanced}")
            
            self._add_to_history("user", enhanced)
            
            messages = [{"role": "system", "content": self.system_prompt}]
            messages.extend(self.conversation_history)
            
            response = await asyncio.to_thread(
                ollama.chat,
                model=self.model_name,
                messages=messages,
                options={
                    "temperature": 0.7,
                    "num_predict": 300,
                    "num_ctx": 4096,
                },
                keep_alive="24h"
            )
            
            raw_answer = response['message']['content']
            print(f"📥 Сырой ответ ({len(raw_answer)} симв.): {raw_answer[:200]}")
            
            # Очищаем ответ
            answer = self._clean_answer(raw_answer)
            
            # 🛡️ Защита от пустых ответов
            if not answer or len(answer) < 3:
                print(f"⚠️  Ответ слишком короткий или пустой!")
                self.conversation_history.pop()
                return "Не смог ответить. Спросите подробнее, пожалуйста."
            
            self._add_to_history("assistant", answer)
            return answer
            
        except Exception as e:
            print(f"⚠️  Ошибка LLM: {e}")
            import traceback
            traceback.print_exc()
            return "Извините, возникли проблемы."
    
    def clear_history(self):
        self.conversation_history = []
        print("🧹 Память очищена")


# Тест
async def main():
    llm = LLMController()
    llm.preload()
    
    print("\n🧪 Тест Qwen 2.5 7B")
    print("=" * 60)
    
    tests = [
        "что такое космос",
        "город",
        "Привет! Как дела?",
        "расскажи факт",
    ]
    
    for q in tests:
        print(f"\n❓ {q}")
        a = await llm.ask(q)
        print(f"💬 ФИНАЛЬНЫЙ: {a}")
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())