"""
Advanced Telegram Group Moderation Bot with Media Support
Requirements: python-telegram-bot[job-queue]==21.5
Install: pip install "python-telegram-bot[job-queue]==21.5"
Note: Use Python 3.9-3.12 (Python 3.13 has compatibility issues)
"""
import asyncio
import json
import re
import base64
from datetime import datetime
from typing import Dict, List, Set, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions, InputMediaPhoto
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters, ConversationHandler
)

# Conversation states
WAITING_MESSAGE, WAITING_INTERVAL, WAITING_BUTTONS, WAITING_MEDIA = range(4)

# Storage class for bot settings
class BotStorage:
    def __init__(self):
        self.data = {
            "recurring_messages": {}, # group_id: [{msg, interval, media, buttons, delete_previous, pin_message, last_sent, last_message_id}]
            "banned_words": {}, # group_id: [word1, word2...]
            "block_links": {}, # group_id: True/False
            "block_mentions": {}, # group_id: True/False
            "auto_replies": {}, # group_id: {trigger: reply_message}
        }
        self.temp_messages = {} # user_id: {text, media, buttons, interval, chat_id, delete_previous, pin_message}
        self.load_data()
   
    def load_data(self):
        try:
            with open('bot_data.json', 'r') as f:
                self.data = json.load(f)
        except FileNotFoundError:
            pass
   
    def save_data(self):
        with open('bot_data.json', 'w') as f:
            json.dump(self.data, f, indent=2)
   
    def get_recurring_messages(self, chat_id: str) -> List:
        return self.data["recurring_messages"].get(chat_id, [])
   
    def add_recurring_message(self, chat_id: str, message_data: dict):
        if chat_id not in self.data["recurring_messages"]:
            self.data["recurring_messages"][chat_id] = []
        self.data["recurring_messages"][chat_id].append(message_data)
        self.save_data()
   
    def remove_recurring_message(self, chat_id: str, index: int):
        if chat_id in self.data["recurring_messages"]:
            if 0 <= index < len(self.data["recurring_messages"][chat_id]):
                self.data["recurring_messages"][chat_id].pop(index)
                self.save_data()
   
    def get_banned_words(self, chat_id: str) -> List[str]:
        return self.data["banned_words"].get(chat_id, [])
   
    def add_banned_word(self, chat_id: str, word: str):
        if chat_id not in self.data["banned_words"]:
            self.data["banned_words"][chat_id] = []
        if word.lower() not in [w.lower() for w in self.data["banned_words"][chat_id]]:
            self.data["banned_words"][chat_id].append(word.lower())
            self.save_data()
   
    def remove_banned_word(self, chat_id: str, word: str):
        if chat_id in self.data["banned_words"]:
            self.data["banned_words"][chat_id] = [
                w for w in self.data["banned_words"][chat_id]
                if w.lower() != word.lower()
            ]
            self.save_data()
   
    def set_block_links(self, chat_id: str, enabled: bool):
        self.data["block_links"][chat_id] = enabled
        self.save_data()
   
    def get_block_links(self, chat_id: str) -> bool:
        return self.data["block_links"].get(chat_id, False)
   
    def set_block_mentions(self, chat_id: str, enabled: bool):
        self.data["block_mentions"][chat_id] = enabled
        self.save_data()
   
    def get_block_mentions(self, chat_id: str) -> bool:
        return self.data["block_mentions"].get(chat_id, False)
    
    def add_auto_reply(self, chat_id: str, trigger: str, reply: str):
        if chat_id not in self.data["auto_replies"]:
            self.data["auto_replies"][chat_id] = {}
        self.data["auto_replies"][chat_id][trigger.lower()] = reply
        self.save_data()
    
    def remove_auto_reply(self, chat_id: str, trigger: str):
        if chat_id in self.data["auto_replies"]:
            self.data["auto_replies"][chat_id].pop(trigger.lower(), None)
            self.save_data()
    
    def get_auto_replies(self, chat_id: str) -> dict:
        return self.data["auto_replies"].get(chat_id, {})

# Initialize storage
storage = BotStorage()

# Check if user is admin
async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> bool:
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ['creator', 'administrator']
    except:
        return False

# Admin check decorator
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message and update.message.chat.type != 'private':
            await update.message.reply_text("⚠️ Please use this command in private chat with me!")
            return
        return await func(update, context)
    return wrapper

# Start command - Main menu
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != 'private':
        await update.message.reply_text("Warning: Please use this command in private chat with me!")
        return
   
    keyboard = [
        [InlineKeyboardButton("Recurring Messages", callback_data="menu_recurring")],
        [InlineKeyboardButton("Banned Words", callback_data="menu_banned_words")],
        [InlineKeyboardButton("Auto Replies", callback_data="menu_auto_replies")],
        [InlineKeyboardButton("Link Blocking", callback_data="menu_links")],
        [InlineKeyboardButton("Mention Blocking", callback_data="menu_mentions")],
        [InlineKeyboardButton("Help", callback_data="menu_help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    welcome_text = (
        "*Advanced Group Moderation Bot*\n\n"
        "Welcome to your bot control panel!\n\n"
        "Features:\n"
        "• Rich recurring messages (text, media, buttons)\n"
        "• Banned words filter\n"
        "• Auto replies (FAQ system)\n"
        "• Link blocking\n"
        "• Mention blocking\n\n"
        "All settings are per-group and can be managed by any group admin."
    )
   
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

# Callback handler for menu navigation
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
   
    data = query.data
   
    # Main menus
    if data == "menu_recurring":
        await show_recurring_menu(query, context)
    elif data == "menu_banned_words":
        await show_banned_words_menu(query, context)
    elif data == "menu_auto_replies":
        await show_auto_replies_menu(query, context)
    elif data == "menu_links":
        await show_links_menu(query, context)
    elif data == "menu_mentions":
        await show_mentions_menu(query, context)
    elif data == "menu_help":
        await show_help(query, context)
    elif data == "back_main":
        await show_main_menu(query, context)
   
    # Recurring messages actions
    elif data.startswith("recurring_"):
        await handle_recurring_action(query, context, data)
   
    # Preview and confirm
    elif data == "preview_message":
        await preview_message(query, context)
    elif data == "confirm_save":
        await confirm_save_message(query, context)
    elif data == "edit_message":
        await edit_message_options(query, context)
   
    # Delete previous option
    elif data == "opt_delete_yes":
        await handle_delete_option(query, context, True)
    elif data == "opt_delete_no":
        await handle_delete_option(query, context, False)
   
    # Pin message option
    elif data == "opt_pin_yes":
        await handle_pin_option(query, context, True)
    elif data == "opt_pin_no":
        await handle_pin_option(query, context, False)
   
    # Link blocking toggle
    elif data.startswith("toggle_links_"):
        await toggle_link_blocking(query, context, data)
   
    # Mention blocking toggle
    elif data.startswith("toggle_mentions_"):
        await toggle_mention_blocking(query, context, data)
   
    # Delete recurring message
    elif data.startswith("delrec_"):
        await delete_recurring_from_button(query, context, data)

async def show_main_menu(query, context):
    keyboard = [
        [InlineKeyboardButton("Recurring Messages", callback_data="menu_recurring")],
        [InlineKeyboardButton("Banned Words", callback_data="menu_banned_words")],
        [InlineKeyboardButton("Auto Replies", callback_data="menu_auto_replies")],
        [InlineKeyboardButton("Link Blocking", callback_data="menu_links")],
        [InlineKeyboardButton("Mention Blocking", callback_data="menu_mentions")],
        [InlineKeyboardButton("Help", callback_data="menu_help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    text = (
        "*Main Menu*\n\n"
        "Select an option to configure your bot:"
    )
   
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_recurring_menu(query, context):
    keyboard = [
        [InlineKeyboardButton("Add New Message", callback_data="recurring_add")],
        [InlineKeyboardButton("View All Messages", callback_data="recurring_list")],
        [InlineKeyboardButton("Back", callback_data="back_main")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    text = (
        "*Recurring Messages Manager*\n\n"
        "Create rich automated messages with:\n"
        "• Custom text (markdown supported)\n"
        "• Photos/Videos/GIFs\n"
        "• Inline buttons with URLs\n"
        "• Live preview before saving\n"
        "• Auto-delete previous message\n"
        "• Auto-pin messages\n\n"
        "Perfect for advertisements and announcements!\n\n"
        "Choose an action:"
    )
   
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_recurring_action(query, context, data):
    if data == "recurring_add":
        # Start conversation for adding message
        user_id = query.from_user.id
        storage.temp_messages[user_id] = {
            'text': None,
            'media': None,
            'media_type': None,
            'buttons': [],
            'interval': None,
            'chat_id': None,
            'delete_previous': False,
            'pin_message': False
        }
       
        text = (
            "*Step 1/7: Choose Group*\n\n"
            "Send me the Chat ID of the group where you want this recurring message.\n\n"
            "Use `/chatid` command in your group to get the ID.\n\n"
            "Format: `-1001234567890`\n\n"
            "Type /cancel to abort."
        )
       
        keyboard = [[InlineKeyboardButton("Cancel", callback_data="menu_recurring")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
       
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        context.user_data['state'] = 'waiting_chatid'
   
    elif data == "recurring_list":
        await show_recurring_list(query, context)

async def show_recurring_list(query, context):
    text = "*Your Recurring Messages*\n\n"
    keyboard = []
    has_messages = False
   
    for chat_id, messages in storage.data["recurring_messages"].items():
        if messages:
            has_messages = True
            text += f"*Group:* `{chat_id}`\n"
            for i, msg in enumerate(messages):
                msg_preview = msg.get('text', 'Media message')[:30]
                has_media = "📸" if msg.get('media') else "📝"
                has_buttons = "🔘" if msg.get('buttons') else ""
                delete_prev = "🗑" if msg.get('delete_previous') else ""
                pin_msg = "📌" if msg.get('pin_message') else ""
                text += f"{i+1}. {has_media}{has_buttons}{delete_prev}{pin_msg} Every {msg['interval']}min: {msg_preview}...\n"
                keyboard.append([
                    InlineKeyboardButton(
                        f"Delete #{i+1} from {chat_id}",
                        callback_data=f"delrec_{chat_id}_{i}"
                    )
                ])
            text += "\n"
   
    if not has_messages:
        text += "No recurring messages configured yet.\n\n"
        text += "Click 'Add New Message' to create one!"
    else:
        text += "\n*Legend:*\n"
        text += "📸 = Has media | 🔘 = Has buttons\n"
        text += "🗑 = Deletes previous | 📌 = Auto-pins\n"
   
    keyboard.append([InlineKeyboardButton("Back", callback_data="menu_recurring")])
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def delete_recurring_from_button(query, context, data):
    parts = data.split('_')
    chat_id = parts[1]
    index = int(parts[2])
   
    storage.remove_recurring_message(chat_id, index)
    await query.answer("Message deleted!")
    await show_recurring_list(query, context)

# Handle delete previous option
async def handle_delete_option(query, context, delete: bool):
    user_id = query.from_user.id
   
    if user_id not in storage.temp_messages:
        await query.answer("No message being created!")
        return
   
    storage.temp_messages[user_id]['delete_previous'] = delete
   
    # Ask about pin option
    keyboard = [
        [InlineKeyboardButton("Yes, Pin Message", callback_data="opt_pin_yes")],
        [InlineKeyboardButton("No, Don't Pin", callback_data="opt_pin_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    await query.edit_message_text(
        "*Auto-Pin Message?*\n\n"
        "Should the bot automatically pin this message every time it's sent?\n\n"
        "*Yes:* Message will be pinned (members get notification)\n"
        "*No:* Message won't be pinned (normal message)\n\n"
        "*Note:* Bot needs 'Pin Messages' permission!\n\n"
        "Choose an option:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# Handle pin option
async def handle_pin_option(query, context, pin: bool):
    user_id = query.from_user.id
   
    if user_id not in storage.temp_messages:
        await query.answer("No message being created!")
        return
   
    storage.temp_messages[user_id]['pin_message'] = pin
    context.user_data['state'] = 'waiting_interval'
   
    await query.edit_message_text(
        "*Step 7/7: Interval*\n\n"
        "How often should I send this message?\n\n"
        "Send the interval in minutes (minimum 1).\n\n"
        "*Example:* `10` for every 10 minutes",
        parse_mode='Markdown'
    )

# Handle text messages for recurring message creation
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != 'private':
        return
   
    user_id = update.effective_user.id
    state = context.user_data.get('state')
   
    if not state or user_id not in storage.temp_messages:
        return
   
    text = update.message.text
   
    if text == '/cancel':
        del storage.temp_messages[user_id]
        context.user_data['state'] = None
        await update.message.reply_text("Cancelled. Use /start to go back to menu.")
        return
   
    if state == 'waiting_chatid':
        # Validate chat ID and check if user is admin
        try:
            chat_id = int(text)
            is_admin = await is_group_admin(update, context, chat_id)
           
            if not is_admin:
                await update.message.reply_text(
                    "Warning: You must be an admin in that group!\n\n"
                    "Please check the chat ID or make sure you're an admin."
                )
                return
           
            storage.temp_messages[user_id]['chat_id'] = str(chat_id)
           
            keyboard = [[InlineKeyboardButton("Cancel", callback_data="menu_recurring")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
           
            await update.message.reply_text(
                "Group verified!\n\n"
                "*Step 2/7: Message Text*\n\n"
                "Now send me the text for your message.\n\n"
                "You can use *markdown* formatting:\n"
                "• `*bold*` for bold\n"
                "• `_italic_` for italic\n"
                "• `[link](url)` for links\n\n"
                "Or send 'skip' if you only want media.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            context.user_data['state'] = 'waiting_text'
           
        except (ValueError, Exception) as e:
            await update.message.reply_text(
                f"Invalid chat ID or error: {str(e)}\n\n"
                "Please send a valid group chat ID like: `-1001234567890`"
            )
   
    elif state == 'waiting_text':
        if text.lower() != 'skip':
            storage.temp_messages[user_id]['text'] = text
       
        keyboard = [[InlineKeyboardButton("Cancel", callback_data="menu_recurring")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
       
        await update.message.reply_text(
            "*Step 3/7: Media (Optional)*\n\n"
            "Send me a photo, video, or GIF for your message.\n\n"
            "Or send 'skip' to continue without media.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        context.user_data['state'] = 'waiting_media'
   
    elif state == 'waiting_buttons':
        if text.lower() == 'skip':
            storage.temp_messages[user_id]['buttons'] = []
        else:
            # Parse buttons format: Text|URL, Text|URL
            try:
                buttons = []
                lines = text.strip().split('\n')
                for line in lines:
                    if '|' in line:
                        btn_text, btn_url = line.split('|', 1)
                        buttons.append({'text': btn_text.strip(), 'url': btn_url.strip()})
               
                storage.temp_messages[user_id]['buttons'] = buttons
            except Exception as e:
                await update.message.reply_text(
                    f"Invalid button format!\n\n"
                    "Use this format:\n"
                    "`Button Text|https://url.com`\n"
                    "`Another Button|https://url2.com`\n\n"
                    "Try again or send 'skip':",
                    parse_mode='Markdown'
                )
                return
       
        # Ask about delete previous option
        keyboard = [
            [InlineKeyboardButton("Yes, Delete Previous", callback_data="opt_delete_yes")],
            [InlineKeyboardButton("No, Keep All", callback_data="opt_delete_no")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
       
        await update.message.reply_text(
            "*Delete Previous Message?*\n\n"
            "Should the bot delete the previous recurring message before sending a new one?\n\n"
            "*Yes:* Only the latest message stays (cleaner group)\n"
            "*No:* All messages stay (message history visible)\n\n"
            "Choose an option:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        context.user_data['state'] = 'waiting_delete_option'
   
    elif state == 'waiting_interval':
        try:
            interval = int(text)
            if interval < 1:
                await update.message.reply_text("Interval must be at least 1 minute!")
                return
           
            storage.temp_messages[user_id]['interval'] = interval
           
            # Show preview
            await show_preview(update, context, user_id)
           
        except ValueError:
            await update.message.reply_text("Please send a valid number!")

# Handle media messages
async def handle_media_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != 'private':
        return
   
    user_id = update.effective_user.id
    state = context.user_data.get('state')
   
    if state != 'waiting_media' or user_id not in storage.temp_messages:
        return
   
    # Get media file
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        media_type = 'photo'
    elif update.message.video:
        file_id = update.message.video.file_id
        media_type = 'video'
    elif update.message.animation:
        file_id = update.message.animation.file_id
        media_type = 'animation'
    else:
        await update.message.reply_text("Unsupported media type. Send photo, video, or GIF.")
        return
   
    storage.temp_messages[user_id]['media'] = file_id
    storage.temp_messages[user_id]['media_type'] = media_type
   
    keyboard = [[InlineKeyboardButton("Cancel", callback_data="menu_recurring")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    await update.message.reply_text(
        "*Step 4/7: Buttons (Optional)*\n\n"
        "Add inline buttons to your message!\n\n"
        "Format (one per line):\n"
        "`Button Text|https://url.com`\n"
        "`Visit Site|https://example.com`\n\n"
        "Or send 'skip' to continue without buttons.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    context.user_data['state'] = 'waiting_buttons'

async def show_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    msg_data = storage.temp_messages[user_id]
   
    text = msg_data.get('text', '')
    media = msg_data.get('media')
    media_type = msg_data.get('media_type')
    buttons = msg_data.get('buttons', [])
    interval = msg_data.get('interval')
    delete_prev = msg_data.get('delete_previous', False)
    pin_msg = msg_data.get('pin_message', False)
   
    # Build keyboard
    keyboard = []
    if buttons:
        for btn in buttons:
            keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
   
    preview_keyboard = [
        [InlineKeyboardButton("Save Message", callback_data="confirm_save")],
        [InlineKeyboardButton("Cancel", callback_data="menu_recurring")]
    ]
   
    settings_info = ""
    if delete_prev:
        settings_info += "🗑 Deletes previous message\n"
    if pin_msg:
        settings_info += "📌 Auto-pins message\n"
   
    await update.message.reply_text(
        f"*PREVIEW MODE*\n\n"
        f"⏱ Interval: Every {interval} minutes\n"
        f"{'📸 Media: Yes' if media else '📝 Text only'}\n"
        f"{'🔘 Buttons: Yes' if buttons else ''}\n"
        f"{settings_info}\n"
        f"━━━━━━━━━━━━━━━━",
        parse_mode='Markdown'
    )
   
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
   
    if media:
        if media_type == 'photo':
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=media,
                caption=text if text else None,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        elif media_type == 'video':
            await context.bot.send_video(
                chat_id=update.effective_chat.id,
                video=media,
                caption=text if text else None,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        elif media_type == 'animation':
            await context.bot.send_animation(
                chat_id=update.effective_chat.id,
                animation=media,
                caption=text if text else None,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
   
    # Confirmation buttons
    confirm_markup = InlineKeyboardMarkup(preview_keyboard)
    await update.message.reply_text(
        "━━━━━━━━━━━━━━━━\n\n"
        "Looks good? Save it!\n"
        "Or cancel to start over.",
        reply_markup=confirm_markup
    )

async def preview_message(query, context):
    user_id = query.from_user.id
    if user_id not in storage.temp_messages:
        await query.answer("No message being created!")
        return
   
    await show_preview_from_callback(query, context, user_id)

async def show_preview_from_callback(query, context, user_id: int):
    msg_data = storage.temp_messages[user_id]
   
    text = msg_data.get('text', '')
    media = msg_data.get('media')
    media_type = msg_data.get('media_type')
    buttons = msg_data.get('buttons', [])
    interval = msg_data.get('interval')
    delete_prev = msg_data.get('delete_previous', False)
    pin_msg = msg_data.get('pin_message', False)
   
    keyboard = []
    if buttons:
        for btn in buttons:
            keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
   
    preview_keyboard = [
        [InlineKeyboardButton("Save Message", callback_data="confirm_save")],
        [InlineKeyboardButton("Cancel", callback_data="menu_recurring")]
    ]
   
    settings_info = ""
    if delete_prev:
        settings_info += "🗑 Deletes previous message\n"
    if pin_msg:
        settings_info += "📌 Auto-pins message\n"
   
    await query.message.reply_text(
        f"*PREVIEW MODE*\n\n"
        f"⏱ Interval: Every {interval} minutes\n"
        f"{'📸 Media: Yes' if media else '📝 Text only'}\n"
        f"{'🔘 Buttons: Yes' if buttons else ''}\n"
        f"{settings_info}\n"
        f"━━━━━━━━━━━━━━━━",
        parse_mode='Markdown'
    )
   
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
   
    if media:
        if media_type == 'photo':
            await context.bot.send_photo(
                chat_id=query.message.chat.id,
                photo=media,
                caption=text if text else None,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        elif media_type == 'video':
            await context.bot.send_video(
                chat_id=query.message.chat.id,
                video=media,
                caption=text if text else None,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        elif media_type == 'animation':
            await context.bot.send_animation(
                chat_id=query.message.chat.id,
                animation=media,
                caption=text if text else None,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
    else:
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text=text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
   
    confirm_markup = InlineKeyboardMarkup(preview_keyboard)
    await query.message.reply_text(
        "━━━━━━━━━━━━━━━━\n\n"
        "Looks good? Save it!",
        reply_markup=confirm_markup
    )

async def confirm_save_message(query, context):
    user_id = query.from_user.id
   
    if user_id not in storage.temp_messages:
        await query.answer("No message to save!")
        return
   
    msg_data = storage.temp_messages[user_id]
    chat_id = msg_data['chat_id']
   
    # Prepare message data for storage
    recurring_data = {
        'text': msg_data.get('text'),
        'media': msg_data.get('media'),
        'media_type': msg_data.get('media_type'),
        'buttons': msg_data.get('buttons', []),
        'interval': msg_data['interval'],
        'delete_previous': msg_data.get('delete_previous', False),
        'pin_message': msg_data.get('pin_message', False),
        'last_sent': 0,
        'last_message_id': None
    }
   
    storage.add_recurring_message(chat_id, recurring_data)
   
    # Clean up
    del storage.temp_messages[user_id]
    context.user_data['state'] = None
   
    settings_text = ""
    if recurring_data['delete_previous']:
        settings_text += "🗑 Will delete previous message\n"
    if recurring_data['pin_message']:
        settings_text += "📌 Will auto-pin message\n"
   
    await query.answer("Message saved!")
    await query.message.reply_text(
        f"*Recurring Message Saved!*\n\n"
        f"📢 Group: `{chat_id}`\n"
        f"⏱ Interval: Every {recurring_data['interval']} minutes\n"
        f"{'📸 With media' if recurring_data['media'] else '📝 Text only'}\n"
        f"{'🔘 With buttons' if recurring_data['buttons'] else ''}\n"
        f"{settings_text}\n"
        f"The bot will start sending this message automatically!\n\n"
        f"⚠️ *Important:* For pin feature, make sure bot has 'Pin Messages' permission!",
        parse_mode='Markdown'
    )
   
    await show_recurring_menu(query, context)

async def show_banned_words_menu(query, context):
    text = (
        "*Banned Words Filter*\n\n"
        "Automatically delete messages containing specific words.\n\n"
        "*Commands:*\n"
        "• `/addword <chat_id> <word>` - Add banned word\n"
        "• `/delword <chat_id> <word>` - Remove banned word\n"
        "• `/listwords <chat_id>` - Show all banned words\n\n"
        "*Example:*\n"
        "`/addword -1001234567890 scam`"
    )
   
    keyboard = [[InlineKeyboardButton("Back", callback_data="back_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_auto_replies_menu(query, context):
    text = (
        "🤖 *Auto Replies (FAQ System)*\n\n"
        "Bot automatically replies when users say specific words!\n\n"
        "*How it works:*\n"
        "User: `hello`\n"
        "Bot: `Hello! Welcome to our group!`\n\n"
        "*Commands:*\n"
        "• `/addreply <chat_id> <trigger> | <reply>` - Add auto reply\n"
        "• `/delreply <chat_id> <trigger>` - Remove auto reply\n"
        "• `/listreplies <chat_id>` - Show all auto replies\n\n"
        "*Example:*\n"
        "`/addreply -1001234567890 hello | Hello! Welcome!`\n"
        "`/addreply -1001234567890 price | Check our website!`\n\n"
        "*Tips:*\n"
        "• Use for FAQs, greetings, common questions\n"
        "• Trigger is case-insensitive\n"
        "• Bot replies instantly!"
    )
   
    keyboard = [[InlineKeyboardButton("Back", callback_data="back_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_links_menu(query, context):
    keyboard = []
   
    for chat_id in storage.data.get("block_links", {}).keys():
        status = "🟢 ON" if storage.data["block_links"][chat_id] else "🔴 OFF"
        keyboard.append([
            InlineKeyboardButton(
                f"{status} Group {chat_id}",
                callback_data=f"toggle_links_{chat_id}"
            )
        ])
   
    keyboard.append([InlineKeyboardButton("Back", callback_data="back_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    text = (
        "*Link Blocking*\n\n"
        "Block ALL links from non-admin members.\n\n"
        "Use: `/setlinks <chat_id> <on/off>`\n\n"
        "*Current Settings:*"
    )
   
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_mentions_menu(query, context):
    keyboard = []
   
    for chat_id in storage.data.get("block_mentions", {}).keys():
        status = "🟢 ON" if storage.data["block_mentions"][chat_id] else "🔴 OFF"
        keyboard.append([
            InlineKeyboardButton(
                f"{status} Group {chat_id}",
                callback_data=f"toggle_mentions_{chat_id}"
            )
        ])
   
    keyboard.append([InlineKeyboardButton("Back", callback_data="back_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    text = (
        "*Mention Blocking*\n\n"
        "Block @username mentions from non-admins.\n\n"
        "Use: `/setmentions <chat_id> <on/off>`\n\n"
        "*Current Settings:*"
    )
   
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def toggle_link_blocking(query, context, data):
    chat_id = data.replace("toggle_links_", "")
    current = storage.get_block_links(chat_id)
    storage.set_block_links(chat_id, not current)
    await query.answer(f"✅ Link blocking {'enabled' if not current else 'disabled'}!")
    await show_links_menu(query, context)

async def toggle_mention_blocking(query, context, data):
    chat_id = data.replace("toggle_mentions_", "")
    current = storage.get_block_mentions(chat_id)
    storage.set_block_mentions(chat_id, not current)
    await query.answer(f"✅ Mention blocking {'enabled' if not current else 'disabled'}!")
    await show_mentions_menu(query, context)

async def show_help(query, context):
    text = (
        "ℹ️ *Bot Help & Setup Guide*\n\n"
        "*📋 Setup Steps:*\n"
        "1. Add bot to your group\n"
        "2. Make bot admin (Delete Messages permission)\n"
        "3. Use `/chatid` in group to get Chat ID\n"
        "4. Configure in private chat with bot\n\n"
        "*🔁 Recurring Messages:*\n"
        "Create rich messages with text, media, and buttons!\n\n"
        "*🤖 Auto Replies:*\n"
        "Set up automatic responses to common questions!\n\n"
        "*⚙️ All Commands:*\n"
        "• `/start` - Control panel\n"
        "• `/chatid` - Get group ID\n"
        "• `/addword <id> <word>` - Ban word\n"
        "• `/delword <id> <word>` - Unban word\n"
        "• `/listwords <id>` - Show banned words\n"
        "• `/addreply <id> <trigger> | <reply>` - Add auto reply\n"
        "• `/delreply <id> <trigger>` - Remove auto reply\n"
        "• `/listreplies <id>` - Show auto replies\n"
        "• `/setlinks <id> <on/off>` - Toggle links\n"
        "• `/setmentions <id> <on/off>` - Toggle mentions\n\n"
        "✨ All group admins can manage settings!"
    )
   
    keyboard = [[InlineKeyboardButton("Back", callback_data="back_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
   
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# Get chat ID command
async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
   
    if chat_type == 'private':
        await update.message.reply_text(
            f"📋 *Your User ID:* `{chat_id}`\n\n"
            "To get a group's ID, use this command in that group!",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"📋 *Group Chat ID:* `{chat_id}`\n\n"
            "Use this ID in bot commands to configure settings.",
            parse_mode='Markdown'
        )

# Add banned word
@admin_only
async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = context.args[0]
        word = ' '.join(context.args[1:])
       
        # Verify user is admin
        is_admin = await is_group_admin(update, context, int(chat_id))
        if not is_admin:
            await update.message.reply_text("⚠️ You must be admin in that group!")
            return
       
        storage.add_banned_word(chat_id, word)
        await update.message.reply_text(
            f"✅ *Banned word added!*\n\n"
            f"Word: `{word}`\n"
            f"Group: `{chat_id}`\n\n"
            f"Messages containing this word will be deleted.",
            parse_mode='Markdown'
        )
    except IndexError:
        await update.message.reply_text(
            "❌ *Usage:*\n"
            "`/addword <chat_id> <word>`\n\n"
            "*Example:*\n"
            "`/addword -1001234567890 scam`",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# Remove banned word
@admin_only
async def del_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = context.args[0]
        word = ' '.join(context.args[1:])
       
        is_admin = await is_group_admin(update, context, int(chat_id))
        if not is_admin:
            await update.message.reply_text("⚠️ You must be admin in that group!")
            return
       
        storage.remove_banned_word(chat_id, word)
        await update.message.reply_text(
            f"✅ *Banned word removed!*\n\n"
            f"Word: `{word}`\n"
            f"Group: `{chat_id}`",
            parse_mode='Markdown'
        )
    except IndexError:
        await update.message.reply_text(
            "❌ *Usage:*\n"
            "`/delword <chat_id> <word>`",
            parse_mode='Markdown'
        )

# List banned words
@admin_only
async def list_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = context.args[0]
       
        is_admin = await is_group_admin(update, context, int(chat_id))
        if not is_admin:
            await update.message.reply_text("⚠️ You must be admin in that group!")
            return
       
        words = storage.get_banned_words(chat_id)
       
        if words:
            text = f"🚫 *Banned words for* `{chat_id}`:\n\n"
            for i, word in enumerate(words, 1):
                text += f"{i}. `{word}`\n"
            text += f"\n*Total: {len(words)} words*"
        else:
            text = f"No banned words for group `{chat_id}`"
       
        await update.message.reply_text(text, parse_mode='Markdown')
    except IndexError:
        await update.message.reply_text(
            "❌ *Usage:*\n"
            "`/listwords <chat_id>`",
            parse_mode='Markdown'
        )

# Add auto reply
@admin_only
async def add_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Parse: /addreply <chat_id> <trigger> | <reply>
        args_text = ' '.join(context.args)
        chat_id, rest = args_text.split(' ', 1)
       
        if '|' not in rest:
            raise ValueError("Missing | separator")
       
        trigger, reply = rest.split('|', 1)
        trigger = trigger.strip()
        reply = reply.strip()
       
        # Verify user is admin
        is_admin = await is_group_admin(update, context, int(chat_id))
        if not is_admin:
            await update.message.reply_text("⚠️ You must be admin in that group!")
            return
       
        storage.add_auto_reply(chat_id, trigger, reply)
        await update.message.reply_text(
            f"✅ *Auto reply added!*\n\n"
            f"Trigger: `{trigger}`\n"
            f"Reply: `{reply}`\n"
            f"Group: `{chat_id}`\n\n"
            f"Now when users say '{trigger}', bot will reply!",
            parse_mode='Markdown'
        )
    except (IndexError, ValueError):
        await update.message.reply_text(
            "❌ *Usage:*\n"
            "`/addreply <chat_id> <trigger> | <reply>`\n\n"
            "*Example:*\n"
            "`/addreply -1001234567890 hello | Hello! Welcome!`\n"
            "`/addreply -1001234567890 price | Visit our website!`",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# Delete auto reply
@admin_only
async def del_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = context.args[0]
        trigger = ' '.join(context.args[1:])
       
        is_admin = await is_group_admin(update, context, int(chat_id))
        if not is_admin:
            await update.message.reply_text("⚠️ You must be admin in that group!")
            return
       
        storage.remove_auto_reply(chat_id, trigger)
        await update.message.reply_text(
            f"✅ *Auto reply removed!*\n\n"
            f"Trigger: `{trigger}`\n"
            f"Group: `{chat_id}`",
            parse_mode='Markdown'
        )
    except IndexError:
        await update.message.reply_text(
            "❌ *Usage:*\n"
            "`/delreply <chat_id> <trigger>`\n\n"
            "*Example:*\n"
            "`/delreply -1001234567890 hello`",
            parse_mode='Markdown'
        )

# List auto replies
@admin_only
async def list_replies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = context.args[0]
       
        is_admin = await is_group_admin(update, context, int(chat_id))
        if not is_admin:
            await update.message.reply_text("⚠️ You must be admin in that group!")
            return
       
        replies = storage.get_auto_replies(chat_id)
       
        if replies:
            text = f"🤖 *Auto replies for* `{chat_id}`:\n\n"
            for i, (trigger, reply) in enumerate(replies.items(), 1):
                reply_preview = reply[:50] + "..." if len(reply) > 50 else reply
                text += f"{i}. `{trigger}` → {reply_preview}\n\n"
            text += f"*Total: {len(replies)} replies*"
        else:
            text = f"No auto replies for group `{chat_id}`"
       
        await update.message.reply_text(text, parse_mode='Markdown')
    except IndexError:
        await update.message.reply_text(
            "❌ *Usage:*\n"
            "`/listreplies <chat_id>`",
            parse_mode='Markdown'
        )

# Set link blocking
@admin_only
async def set_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = context.args[0]
        enabled = context.args[1].lower() in ['on', 'true', '1', 'yes', 'enable']
       
        is_admin = await is_group_admin(update, context, int(chat_id))
        if not is_admin:
            await update.message.reply_text("⚠️ You must be admin in that group!")
            return
       
        storage.set_block_links(chat_id, enabled)
        status = "🟢 ENABLED" if enabled else "🔴 DISABLED"
       
        await update.message.reply_text(
            f"✅ *Link blocking {status}*\n\n"
            f"Group: `{chat_id}`\n\n"
            f"{'All links from non-admins will be deleted!' if enabled else 'Links are now allowed.'}",
            parse_mode='Markdown'
        )
    except IndexError:
        await update.message.reply_text(
            "❌ *Usage:*\n"
            "`/setlinks <chat_id> <on/off>`\n\n"
            "*Example:*\n"
            "`/setlinks -1001234567890 on`",
            parse_mode='Markdown'
        )

# Set mention blocking
@admin_only
async def set_mentions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = context.args[0]
        enabled = context.args[1].lower() in ['on', 'true', '1', 'yes', 'enable']
       
        is_admin = await is_group_admin(update, context, int(chat_id))
        if not is_admin:
            await update.message.reply_text("⚠️ You must be admin in that group!")
            return
       
        storage.set_block_mentions(chat_id, enabled)
        status = "🟢 ENABLED" if enabled else "🔴 DISABLED"
       
        await update.message.reply_text(
            f"✅ *Mention blocking {status}*\n\n"
            f"Group: `{chat_id}`\n\n"
            f"{'@username mentions from non-admins will be deleted!' if enabled else 'Mentions are now allowed.'}",
            parse_mode='Markdown'
        )
    except IndexError:
        await update.message.reply_text(
            "❌ *Usage:*\n"
            "`/setmentions <chat_id> <on/off>`",
            parse_mode='Markdown'
        )

# Message filter in groups
async def filter_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.chat.type == 'private':
        return
   
    chat_id = str(update.effective_chat.id)
    message = update.message
    user_id = update.effective_user.id
   
    # Check if user is admin
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        is_admin_user = member.status in ['creator', 'administrator']
    except:
        is_admin_user = False
   
    text = message.text or message.caption or ""
    text_lower = text.lower()
   
    # Check for auto replies FIRST (works for everyone including admins)
    auto_replies = storage.get_auto_replies(chat_id)
    for trigger, reply in auto_replies.items():
        if trigger in text_lower:
            try:
                await message.reply_text(reply, parse_mode='Markdown')
            except:
                await message.reply_text(reply)  # Fallback without markdown
            break  # Only reply once per message
   
    # Admins bypass deletion filters (but not auto-replies above)
    if is_admin_user:
        return
   
    should_delete = False
    reason = ""
   
    # Check for links
    if storage.get_block_links(chat_id):
        url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        tg_pattern = r't\.me/|telegram\.me/|telegram\.dog/'
       
        if re.search(url_pattern, text, re.IGNORECASE) or re.search(tg_pattern, text, re.IGNORECASE):
            should_delete = True
            reason = "🔗 links"
   
    # Check for mentions
    if storage.get_block_mentions(chat_id) and not should_delete:
        if re.search(r'@\w+', text):
            should_delete = True
            reason = "📢 mentions"
   
    # Check for banned words
    if not should_delete:
        banned_words = storage.get_banned_words(chat_id)
        for word in banned_words:
            if word in text_lower:
                should_delete = True
                reason = f"🚫 banned word"
                break
   
    # Delete if necessary
    if should_delete:
        try:
            await message.delete()
            # Send temporary warning
            warning = await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Message deleted ({reason})",
                reply_to_message_id=None
            )
            await asyncio.sleep(3)
            try:
                await warning.delete()
            except:
                pass
        except Exception as e:
            print(f"Error deleting message: {e}")

# Recurring message sender
async def send_recurring_messages(context: ContextTypes.DEFAULT_TYPE):
    current_time = datetime.now().timestamp()
   
    for chat_id, messages in storage.data["recurring_messages"].items():
        for msg_data in messages:
            interval_seconds = msg_data["interval"] * 60
            last_sent = msg_data.get("last_sent", 0)
           
            if current_time - last_sent >= interval_seconds:
                try:
                    # Delete previous message if option is enabled
                    if msg_data.get('delete_previous') and msg_data.get('last_message_id'):
                        try:
                            await context.bot.delete_message(
                                chat_id=chat_id,
                                message_id=msg_data['last_message_id']
                            )
                        except Exception as e:
                            print(f"Could not delete previous message: {e}")
                   
                    # Build keyboard if buttons exist
                    keyboard = []
                    if msg_data.get('buttons'):
                        for btn in msg_data['buttons']:
                            keyboard.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
                   
                    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
                   
                    # Send message based on type
                    text = msg_data.get('text')
                    media = msg_data.get('media')
                    media_type = msg_data.get('media_type')
                    sent_message = None
                   
                    if media and media_type:
                        if media_type == 'photo':
                            sent_message = await context.bot.send_photo(
                                chat_id=chat_id,
                                photo=media,
                                caption=text if text else None,
                                reply_markup=reply_markup,
                                parse_mode='Markdown'
                            )
                        elif media_type == 'video':
                            sent_message = await context.bot.send_video(
                                chat_id=chat_id,
                                video=media,
                                caption=text if text else None,
                                reply_markup=reply_markup,
                                parse_mode='Markdown'
                            )
                        elif media_type == 'animation':
                            sent_message = await context.bot.send_animation(
                                chat_id=chat_id,
                                animation=media,
                                caption=text if text else None,
                                reply_markup=reply_markup,
                                parse_mode='Markdown'
                            )
                    elif text:
                        sent_message = await context.bot.send_message(
                            chat_id=chat_id,
                            text=text,
                            reply_markup=reply_markup,
                            parse_mode='Markdown'
                        )
                   
                    # Pin message if option is enabled
                    if sent_message and msg_data.get('pin_message'):
                        try:
                            await context.bot.pin_chat_message(
                                chat_id=chat_id,
                                message_id=sent_message.message_id,
                                disable_notification=False
                            )
                        except Exception as e:
                            print(f"Could not pin message: {e}")
                   
                    # Store message ID and update timestamp
                    if sent_message:
                        msg_data["last_message_id"] = sent_message.message_id
                    msg_data["last_sent"] = current_time
                    storage.save_data()
                   
                except Exception as e:
                    print(f"Error sending recurring message to {chat_id}: {e}")

# Main function
def main():
    import os
    TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN_HERE"
   
    if TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ERROR: Bot token not set!")
        print("   Set BOT_TOKEN environment variable in Railway")
        print("   Or replace 'YOUR_BOT_TOKEN_HERE' with your actual token")
        return
   
    print(f"🔑 Using bot token: {TOKEN[:10]}...{TOKEN[-10:]}")
   
    application = Application.builder().token(TOKEN).build()
   
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("chatid", chatid))
    application.add_handler(CommandHandler("addword", add_word))
    application.add_handler(CommandHandler("delword", del_word))
    application.add_handler(CommandHandler("listwords", list_words))
    application.add_handler(CommandHandler("addreply", add_reply))
    application.add_handler(CommandHandler("delreply", del_reply))
    application.add_handler(CommandHandler("listreplies", list_replies))
    application.add_handler(CommandHandler("setlinks", set_links))
    application.add_handler(CommandHandler("setmentions", set_mentions))
   
    # Callback query handler
    application.add_handler(CallbackQueryHandler(button_callback))
   
    # Text input handler for recurring message creation
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_text_input
    ))
   
    # Media input handler
    application.add_handler(MessageHandler(
        (filters.PHOTO | filters.VIDEO | filters.ANIMATION) & filters.ChatType.PRIVATE,
        handle_media_input
    ))
   
    # Message filter for groups
    application.add_handler(MessageHandler(
        (filters.TEXT | filters.CAPTION) & ~filters.COMMAND & ~filters.ChatType.PRIVATE,
        filter_message
    ))
   
    # Job queue for recurring messages (check every 30 seconds)
    job_queue = application.job_queue
    job_queue.run_repeating(send_recurring_messages, interval=30, first=10)
   
    # Start bot
    print("🤖 Bot is running...")
    print("📋 Features:")
    print("   ✅ Rich recurring messages (text, media, buttons)")
    print("   ✅ Auto-delete previous & auto-pin")
    print("   ✅ Live preview before saving")
    print("   ✅ Banned words filter")
    print("   ✅ Auto replies (FAQ system)")
    print("   ✅ Link & mention blocking")
    print("   ✅ Multi-admin support")
    print("   ✅ User-friendly panel")
    print("\n⚙️  Send /start in private chat to configure!")
   
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
