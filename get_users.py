import asyncio
from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import (
    ChannelParticipantsRecent,
    ChannelParticipantsAdmins,
    ChannelParticipantsSearch,
    ChannelParticipantsBanned,
    ChannelParticipantsKicked,
    ChannelParticipantsBots,
    ChannelParticipantCreator,
    ChannelParticipantAdmin,
    ChannelParticipant
)
from telethon.errors import ChatAdminRequiredError, ChannelPrivateError, FloodWaitError
from datetime import datetime
import csv
import time

# Конфигурация
SESSION_FILE = 'campaign_tracker.session'
API_ID = # ID HERE
API_HASH = "" #HASH HERE

class TelegramParticipantsExtractor:
    def __init__(self, api_id, api_hash, session_file):
        self.client = TelegramClient(session_file, api_id, api_hash)

    async def get_all_participants_aggressive(self, chat_id, limit=None):
        """
        Получает всех участников используя iter_participants с aggressive=True
        Это более эффективный способ для больших каналов
        """
        all_participants = []
        count = 0

        try:
            print("Начинаем агрессивное сканирование участников...")

            async for user in self.client.iter_participants(
                chat_id,
                limit=limit,
                aggressive=True  # Ключевой параметр для получения всех участников
            ):
                count += 1

                participant_info = {
                    'user_id': user.id,
                    'username': user.username or '',
                    'first_name': user.first_name or '',
                    'last_name': user.last_name or '',
                    'phone': user.phone or '',
                    'is_bot': user.bot,
                    'is_verified': user.verified,
                    'is_premium': getattr(user, 'premium', False),
                    'is_scam': getattr(user, 'scam', False),
                    'is_fake': getattr(user, 'fake', False),
                    'is_restricted': getattr(user, 'restricted', False),
                    'last_seen': getattr(user.status, 'was_online', None) if hasattr(user, 'status') else None,
                    'participant_type': 'Member',
                    'join_date': None,  # iter_participants не предоставляет дату вступления
                    'join_date_formatted': 'Не определено',
                }

                all_participants.append(participant_info)

                # Показываем прогресс каждые 100 участников
                if count % 100 == 0:
                    print(f"Получено участников: {count}")

                # Небольшая задержка для избежания rate limiting
                if count % 50 == 0:
                    await asyncio.sleep(0.1)

        except FloodWaitError as e:
            print(f"Превышен лимит запросов. Ожидание {e.seconds} секунд...")
            await asyncio.sleep(e.seconds)
            # Рекурсивно продолжаем после ожидания
            remaining_participants = await self.get_all_participants_aggressive(
                chat_id,
                limit=(limit - len(all_participants)) if limit else None
            )
            all_participants.extend(remaining_participants)

        except ChatAdminRequiredError:
            print("Ошибка: Требуются права администратора для получения списка участников")
            return []
        except ChannelPrivateError:
            print("Ошибка: Канал приватный или недоступен")
            return []
        except Exception as e:
            print(f"Ошибка при получении участников: {e}")
            print(f"Получено участников до ошибки: {len(all_participants)}")

        print(f"Всего получено участников: {len(all_participants)}")
        return all_participants

    async def get_all_participants_combined(self, chat_id, limit=None):
        """
        Комбинированный подход: сначала пытается агрессивный метод,
        затем фолбэк на стандартные методы
        """
        print("Пробуем агрессивный метод...")
        participants = await self.get_all_participants_aggressive(chat_id, limit)

        if not participants:
            print("Агрессивный метод не сработал. Пробуем стандартные методы...")
            participants = await self.get_all_participants_standard(chat_id, limit)

        return participants

    async def get_all_participants_standard(self, chat_id, limit=None, filter_type='recent', search_query=''):
        """
        Стандартный метод получения участников (исправленная версия с обработкой разных типов участников)
        """
        # Определяем тип фильтра
        try:
            if filter_type == 'recent':
                filter_obj = ChannelParticipantsRecent()
            elif filter_type == 'admins':
                filter_obj = ChannelParticipantsAdmins()
            elif filter_type == 'search':
                filter_obj = ChannelParticipantsSearch(search_query)
            elif filter_type == 'banned':
                filter_obj = ChannelParticipantsBanned(search_query)
            elif filter_type == 'kicked':
                filter_obj = ChannelParticipantsKicked(search_query)
            elif filter_type == 'bots':
                filter_obj = ChannelParticipantsBots()
            else:
                filter_obj = ChannelParticipantsRecent()
        except Exception as e:
            print(f"Ошибка при создании фильтра: {e}")
            filter_obj = ChannelParticipantsRecent()

        all_participants = []
        offset = 0
        batch_size = 200
        consecutive_empty_batches = 0
        max_empty_batches = 3

        try:
            while True:
                print(f"Получение участников: offset={offset}, загружено={len(all_participants)}")

                try:
                    participants = await self.client(GetParticipantsRequest(
                        channel=chat_id,
                        filter=filter_obj,
                        offset=offset,
                        limit=batch_size,
                        hash=0
                    ))
                except FloodWaitError as e:
                    print(f"Превышен лимит запросов. Ожидание {e.seconds} секунд...")
                    await asyncio.sleep(e.seconds)
                    continue

                if not participants.participants:
                    consecutive_empty_batches += 1
                    if consecutive_empty_batches >= max_empty_batches:
                        print("Достигнут конец списка участников")
                        break
                    offset += batch_size
                    continue
                else:
                    consecutive_empty_batches = 0

                current_batch_size = len(participants.participants)
                print(f"Получено участников в этом батче: {current_batch_size}")

                users_dict = {user.id: user for user in participants.users}

                for participant in participants.participants:
                    user = users_dict.get(participant.user_id)
                    if user:
                        # Получаем дату вступления с проверкой типа участника
                        join_date = None
                        join_date_formatted = 'Не определено'

                        if isinstance(participant, ChannelParticipantCreator):
                            # У создателя нет атрибута date - используем дату создания канала или None
                            join_date = None
                            join_date_formatted = 'Создатель канала'
                        elif isinstance(participant, (ChannelParticipantAdmin, ChannelParticipant)):
                            # У обычных участников и админов есть дата
                            if hasattr(participant, 'date') and participant.date:
                                join_date = participant.date
                                join_date_formatted = participant.date.strftime('%Y-%m-%d %H:%M:%S')

                        participant_info = {
                            'user_id': user.id,
                            'username': user.username or '',
                            'first_name': user.first_name or '',
                            'last_name': user.last_name or '',
                            'phone': user.phone or '',
                            'is_bot': user.bot,
                            'is_verified': user.verified,
                            'is_premium': getattr(user, 'premium', False),
                            'is_scam': getattr(user, 'scam', False),
                            'is_fake': getattr(user, 'fake', False),
                            'is_restricted': getattr(user, 'restricted', False),
                            'join_date': join_date,
                            'join_date_formatted': join_date_formatted,
                            'participant_type': type(participant).__name__,
                            'is_admin': isinstance(participant, (ChannelParticipantAdmin, ChannelParticipantCreator)),
                            'is_creator': isinstance(participant, ChannelParticipantCreator),
                        }

                        # Добавляем права администратора, если есть
                        if hasattr(participant, 'admin_rights') and participant.admin_rights:
                            participant_info['admin_rights'] = {
                                'can_edit_messages': participant.admin_rights.edit_messages,
                                'can_delete_messages': participant.admin_rights.delete_messages,
                                'can_ban_users': participant.admin_rights.ban_users,
                                'can_invite_users': participant.admin_rights.invite_users,
                                'can_pin_messages': participant.admin_rights.pin_messages,
                                'can_add_admins': participant.admin_rights.add_admins,
                            }

                        all_participants.append(participant_info)

                offset += current_batch_size

                if limit and len(all_participants) >= limit:
                    all_participants = all_participants[:limit]
                    print(f"Достигнут лимит: {limit}")
                    break

                # Адаптивная задержка
                await asyncio.sleep(0.1 if current_batch_size == batch_size else 0.5)

        except ChatAdminRequiredError:
            print("Ошибка: Требуются права администратора для получения списка участников")
            return []
        except ChannelPrivateError:
            print("Ошибка: Канал приватный или недоступен")
            return []
        except Exception as e:
            print(f"Ошибка при получении участников: {e}")
            print(f"Тип ошибки: {type(e).__name__}")

            if filter_type == 'recent':
                print("Попытка получить только администраторов...")
                return await self.get_all_participants_standard(chat_id, limit, 'admins')
            elif filter_type == 'admins':
                print("Попытка получить только ботов...")
                return await self.get_all_participants_standard(chat_id, limit, 'bots')
            return []

        print(f"Всего загружено участников: {len(all_participants)}")
        return all_participants

    def normalize_chat_id(self, chat_id):
        """
        Нормализует ID чата для правильного формата Telegram
        """
        if isinstance(chat_id, str):
            chat_id = chat_id.strip()

            # Если это username, оставляем как есть
            if chat_id.startswith('@'):
                return chat_id

            # Если это числовой ID как строка
            if chat_id.lstrip('-').isdigit():
                chat_id = int(chat_id)
            else:
                return chat_id  # Возвращаем как есть, если не можем распознать

        # Если ID отрицательный и очень большой (супергруппа/канал)
        if isinstance(chat_id, int) and chat_id < -1000000000000:
            # Преобразуем в правильный формат для супергрупп
            return int(str(chat_id)[4:])  # Убираем префикс -100

        return chat_id

    async def get_channel_info_alternative(self, chat_id):
        """
        Альтернативный способ получения информации о канале
        """
        # Нормализуем chat_id
        normalized_chat_id = self.normalize_chat_id(chat_id)

        # Пробуем разные варианты ID
        chat_variants = [
            normalized_chat_id,
            chat_id,  # Оригинальный ID
        ]

        # Если это числовой ID, добавляем варианты с префиксами
        if isinstance(normalized_chat_id, int):
            chat_variants.extend([
                -1000000000000 - abs(normalized_chat_id),  # Формат супергруппы
                -abs(normalized_chat_id),  # Отрицательный ID
                abs(normalized_chat_id),   # Положительный ID
            ])

        for variant in chat_variants:
            try:
                print(f"Пробуем получить информацию с ID: {variant}")
                full_channel = await self.client.get_entity(variant)

                try:
                    from telethon.tl.functions.channels import GetFullChannelRequest
                    full_info = await self.client(GetFullChannelRequest(channel=variant))

                    return {
                        'basic_info': {
                            'id': full_channel.id,
                            'title': full_channel.title,
                            'username': getattr(full_channel, 'username', None),
                            'type': type(full_channel).__name__,
                            'access_hash': getattr(full_channel, 'access_hash', None),
                            'working_id': variant,  # ID который работает
                        },
                        'full_info': {
                            'participants_count': full_info.full_chat.participants_count,
                            'about': full_info.full_chat.about,
                            'can_view_participants': full_info.full_chat.can_view_participants,
                            'can_set_username': full_info.full_chat.can_set_username,
                            'can_set_stickers': full_info.full_chat.can_set_stickers,
                        }
                    }
                except Exception as e:
                    print(f"Не удалось получить расширенную информацию для {variant}: {e}")
                    return {
                        'basic_info': {
                            'id': full_channel.id,
                            'title': full_channel.title,
                            'username': getattr(full_channel, 'username', None),
                            'type': type(full_channel).__name__,
                            'working_id': variant,  # ID который работает
                        },
                        'full_info': None
                    }
            except Exception as e:
                print(f"Не удалось получить информацию с ID {variant}: {e}")
                continue

        print("Не удалось найти чат ни с одним из вариантов ID")
        return None

    async def save_to_csv(self, participants, filename):
        """Сохраняет участников в CSV файл"""
        if not participants:
            print("Нет данных для сохранения")
            return

        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'user_id', 'username', 'first_name', 'last_name', 'phone',
                'is_bot', 'is_verified', 'is_premium', 'is_scam', 'is_fake',
                'is_restricted', 'join_date_formatted', 'participant_type',
                'is_admin', 'is_creator'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for participant in participants:
                row = {k: v for k, v in participant.items() if k in fieldnames}
                writer.writerow(row)

        print(f"Данные сохранены в файл: {filename}")

    async def print_participants(self, participants, show_details=False):
        """Выводит информацию об участниках"""
        if not participants:
            print("Участники не найдены")
            return

        print(f"\nВсего участников: {len(participants)}")
        print("-" * 80)

        # Статистика
        bots = sum(1 for p in participants if p['is_bot'])
        verified = sum(1 for p in participants if p['is_verified'])
        premium = sum(1 for p in participants if p['is_premium'])
        admins = sum(1 for p in participants if p.get('is_admin', False))
        creators = sum(1 for p in participants if p.get('is_creator', False))

        print(f"Статистика:")
        print(f"  Ботов: {bots}")
        print(f"  Верифицированных: {verified}")
        print(f"  Premium пользователей: {premium}")
        print(f"  Администраторов: {admins}")
        print(f"  Создателей: {creators}")
        print("-" * 80)

        for i, participant in enumerate(participants, 1):
            name = f"{participant['first_name']} {participant['last_name']}".strip()
            username = f"@{participant['username']}" if participant['username'] else "Без username"
            join_date = participant['join_date_formatted'] or "Дата неизвестна"

            print(f"{i}. {name} ({username})")
            print(f"   ID: {participant['user_id']}")
            print(f"   Дата вступления: {join_date}")

            if show_details:
                print(f"   Бот: {'Да' if participant.get('is_bot') else 'Нет'}")
                print(f"   Верифицирован: {'Да' if participant.get('is_verified') else 'Нет'}")
                print(f"   Premium: {'Да' if participant.get('is_premium') else 'Нет'}")
                print(f"   Администратор: {'Да' if participant.get('is_admin') else 'Нет'}")
                print(f"   Создатель: {'Да' if participant.get('is_creator') else 'Нет'}")
                print(f"   Тип участника: {participant.get('participant_type', 'Unknown')}")
                print(f"   Скам: {'Да' if participant.get('is_scam') else 'Нет'}")
                print(f"   Фейк: {'Да' if participant.get('is_fake') else 'Нет'}")

            print("-" * 40)

async def main():
    extractor = TelegramParticipantsExtractor(API_ID, API_HASH, SESSION_FILE)

    await extractor.client.start()

    # Print session information
    try:
        # Get session filename from the session object
        if hasattr(extractor.client.session, 'filename'):
            print(f"Session file: {extractor.client.session.filename}")
        else:
            print(f"Session file: {SESSION_FILE}")

        # Get current user info
        me = await extractor.client.get_me()
        print(f"Logged in as: {me.first_name} {me.last_name or ''} (@{me.username or 'no_username'})")
        print(f"User ID: {me.id}")
        print(f"Phone: {me.phone or 'Not available'}")
        print("-" * 50)
    except Exception as e:
        print(f"Could not get session info: {e}")
        print(f"Using session file: {SESSION_FILE}")
        print("-" * 50)

    try:
        chat_id = input("Введите ID чата или username (например, @channel_name): ")

        # Получаем информацию о чате
        chat_info = await extractor.get_channel_info_alternative(chat_id)
        working_id = chat_id  # По умолчанию используем введенный ID

        if chat_info:
            basic = chat_info['basic_info']
            full = chat_info.get('full_info')
            working_id = basic.get('working_id', chat_id)  # Используем рабочий ID

            print(f"Информация о чате:")
            print(f"  Название: {basic['title']}")
            print(f"  ID: {basic['id']}")
            print(f"  Рабочий ID: {working_id}")
            print(f"  Username: {basic['username'] or 'Отсутствует'}")
            print(f"  Тип: {basic['type']}")

            if full:
                print(f"  Количество участников: {full['participants_count']}")
                print(f"  Можно просматривать участников: {full['can_view_participants']}")
                print(f"  Описание: {full['about'][:100]}..." if full['about'] else "  Описание: Отсутствует")
        else:
            print("Попробуйте следующие варианты:")
            print("1. Если это публичный канал, используйте @username")
            print("2. Для приватных каналов попробуйте получить ссылку приглашения")
            print("3. Убедитесь, что у вас есть доступ к каналу")
            return

        # Выбираем метод получения участников
        print("\nВыберите метод получения участников:")
        print("1. Агрессивный метод (iter_participants с aggressive=True) - рекомендуется")
        print("2. Стандартный метод (GetParticipantsRequest)")
        print("3. Комбинированный подход")

        method = input("Выберите метод (1/2/3): ").strip()

        print("\nПолучение участников...")

        # Используем рабочий ID для получения участников
        if method == "1":
            participants = await extractor.get_all_participants_aggressive(working_id)
        elif method == "2":
            participants = await extractor.get_all_participants_standard(working_id, filter_type='recent')
        else:  # method == "3" или любое другое значение
            participants = await extractor.get_all_participants_combined(working_id)

        if participants:
            # Сортируем по ID (или другому критерию, если дата недоступна)
            participants.sort(key=lambda x: x['user_id'])

            show_details = input("\nПоказать подробную информацию? (y/n): ").lower() == 'y'
            await extractor.print_participants(participants, show_details)

            save_csv = input("\nСохранить в CSV файл? (y/n): ").lower() == 'y'
            if save_csv:
                chat_id_for_file = chat_info['basic_info']['id'] if chat_info and 'basic_info' in chat_info else 'unknown'
                filename = f"participants_{chat_id_for_file}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                await extractor.save_to_csv(participants, filename)
        else:
            print("Участники не найдены или недоступны для данного канала.")
            print("Возможные причины:")
            print("- Канал не позволяет просматривать участников")
            print("- Нет прав администратора")
            print("- Канал имеет ограничения по конфиденциальности")

    except KeyboardInterrupt:
        print("\nПрерывание пользователем")
    except Exception as e:
        print(f"Ошибка: {e}")
    finally:
        await extractor.client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
