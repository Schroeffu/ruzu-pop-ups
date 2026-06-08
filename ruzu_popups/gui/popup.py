# Copyright 2020 Charles Henry
from aqt.webview import AnkiWebView
from PyQt6 import QtCore
from aqt import Qt, QWidget, QGridLayout, QPushButton, QDialog, QHBoxLayout, QLineEdit, QLabel
from ..anki_utils import AnkiUtils
import logging
import re
import html


class RuzuPopup(QDialog):

    def __init__(self, parent):
        self.parent = parent
        self.anki_utils = AnkiUtils()
        self.current_card_id = None
        self.cur_button_count = 0
        self.typing_mode = False
        self.pre_reveal_mode = False
        self.last_typed_answer = ''
        self.logger = logging.getLogger(__name__.split('.')[0])

        # popup_window (QWidget)
        # -grid (QGridLayout)
        # --card_view (QWebEngineView)
        # --bottom_grid (QGridLayout)
        # ---buttons self.btn[0~3] (QPushButton)

        ###
        # Top level Pop-up Window
        ###
        parent.popup_window = self.popup_window = QWidget()
        self.popup_window.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.popup_window.setWindowFlag(QtCore.Qt.WindowType.FramelessWindowHint)  # Hide the title bar
        self.popup_window.setWindowTitle("Anki Review")  # Set the title (visible in windows taskbar)
        self.popup_window.setGeometry(0, 0, 400, 300)  # Set window geometry

        ###
        # Card View
        ###
        parent.card_view = self.card_view = AnkiWebView()

        ###
        # Buttons
        ###
        btn_width = 100
        btn_height = 20
        btn_padding = 20
        self.btn = []
        self.btn.append(QPushButton(text="Again"))
        self.btn[0].clicked.connect(lambda _: self.send_answer("Again"))
        self.btn[0].setGeometry(btn_padding, btn_padding, btn_width, btn_height)
        self.btn.append(QPushButton(text="Hard"))
        self.btn[1].clicked.connect(lambda _: self.send_answer("Hard"))
        self.btn[1].setGeometry(btn_padding, btn_padding, btn_width, btn_height)
        self.btn.append(QPushButton(text="Good"))
        self.btn[2].clicked.connect(lambda _: self.send_answer("Good"))
        self.btn[2].setGeometry(btn_padding, btn_padding, btn_width, btn_height)
        self.btn.append(QPushButton(text="Easy"))
        self.btn[3].clicked.connect(lambda _: self.send_answer("Easy"))
        self.btn[3].setGeometry(btn_padding, btn_padding, btn_width, btn_height)
        self.btn.append(QPushButton(text="Show Answer"))
        self.btn[4].setGeometry(btn_padding, btn_padding, btn_width, btn_height)
        self.btn[4].clicked.connect(lambda _: self.show_answer_popup())
        self.btn.append(QPushButton(text="Reveal Question"))
        self.btn[5].setGeometry(btn_padding, btn_padding, btn_width, btn_height)
        self.btn[5].clicked.connect(lambda _: self.show_question_popup())
        self.typing_toggle_btn = QPushButton(text="Self-typing: OFF")
        self.typing_toggle_btn.setMinimumWidth(140)
        self.typing_toggle_btn.setToolTip("Self-typing: OFF")
        self.typing_toggle_btn.clicked.connect(lambda _: self.toggle_typing_mode())
        self.answer_input = QLineEdit()
        self.answer_input.setPlaceholderText("Type your answer...")
        self.answer_input.returnPressed.connect(self.show_answer_popup)
        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.feedback_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        self._apply_typing_toggle_ui()

        ###
        # Layout management - Add objects to main pop-up window
        ###
        parent.grid = self.grid = QGridLayout()
        parent.bottom_grid = self.bottom_grid = QHBoxLayout()
        # self.bottom_grid.setVerticalSpacing(10)
        self.bottom_grid.setContentsMargins(10, 5, 10, 10)
        for i in range(4):
            self.bottom_grid.addWidget(self.btn[i])
        parent.bottom_grid_2 = self.bottom_grid_2 = QHBoxLayout()  # Used to hide buttons when needed
        parent.bottom_wid_2 = self.bottom_wid_2 = QWidget()  # Used to hide buttons when needed
        self.bottom_wid_2.setLayout(self.bottom_grid_2)  # Used to hide buttons when needed
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.addWidget(self.card_view)
        self.grid.addLayout(self.bottom_grid, 1, 0)
        self.grid.addWidget(self.feedback_label, 2, 0)
        self.popup_window.setLayout(self.grid)

    def set_card_position(self):
        # Move to bottom right of screen
        # https://stackoverflow.com/questions/28322073/move-qmessagebox-to-bottom-right-corner-of-the-screen
        # https://forum.qt.io/topic/134570/qapplication-desktop-screengeometry-not-work-in-qt6
        screen_geometry = self.parent.app.primaryScreen().availableGeometry()
        screen_geo = screen_geometry.bottomRight()
        msg_geo = self.popup_window.frameGeometry()
        msg_geo.moveBottomRight(screen_geo)
        self.popup_window.move(msg_geo.topLeft())

    def show_show_button(self):
        self.pre_reveal_mode = True
        self._clear_bottom_controls()
        if self.typing_mode:
            self.bottom_grid.addWidget(self.answer_input)
            self.answer_input.setFocus()
        self.bottom_grid.addWidget(self.btn[5])
        self.bottom_grid.addWidget(self.typing_toggle_btn)

    def show_question_button(self):
        self.pre_reveal_mode = False
        self._clear_bottom_controls()
        if self.typing_mode:
            self.btn[4].setText("Check")
            self.bottom_grid.addWidget(self.answer_input)
            self.bottom_grid.addWidget(self.btn[4])
        else:
            self.btn[4].setText("Show Answer")
            self.bottom_grid.addWidget(self.btn[4])
        self.bottom_grid.addWidget(self.typing_toggle_btn)

    def show_answer_buttons(self):
        # TODO - Take in actual buttons tuple?
        self.pre_reveal_mode = False
        self._clear_bottom_controls()
        if self.cur_button_count == 2:
            self.bottom_grid.addWidget(self.btn[0])  # Again
            self.bottom_grid.addWidget(self.btn[2])  # Good
        elif self.cur_button_count == 3:
            self.bottom_grid.addWidget(self.btn[0])  # Again
            self.bottom_grid.addWidget(self.btn[2])  # Good
            self.bottom_grid.addWidget(self.btn[3])  # Easy
        else:
            for i in range(4):
                self.bottom_grid.addWidget(self.btn[i])  # Again, Hard, Good, Easy

    def _clear_bottom_controls(self):
        for i in range(6):
            self.bottom_grid_2.addWidget(self.btn[i])  # Remove all buttons
        self.bottom_grid_2.addWidget(self.typing_toggle_btn)
        self.bottom_grid_2.addWidget(self.answer_input)

    def _apply_typing_toggle_ui(self):
        if self.typing_mode:
            self.typing_toggle_btn.setText("Self-typing: ON")
            self.typing_toggle_btn.setToolTip("Self-typing: ON")
            self.typing_toggle_btn.setStyleSheet("font-weight: bold;")
        else:
            self.typing_toggle_btn.setText("Self-typing: OFF")
            self.typing_toggle_btn.setToolTip("Self-typing: OFF")
            self.typing_toggle_btn.setStyleSheet("")

    def _set_feedback(self, evaluation):
        if evaluation['is_correct'] and not evaluation['accepted_with_one_error']:
            self.feedback_label.setText('Correct: "%s"' % evaluation['typed'])
            self.feedback_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #1c7c35;")
            return

        if evaluation['accepted_with_one_error']:
            self.feedback_label.setText(
                'Almost correct (1 character tolerated).<br>'
                'Your answer: %s<br>'
                'Correct answer: %s' % (evaluation['typed_markup'], evaluation['expected_markup'])
            )
            self.feedback_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #9a3412;")
            return

        self.feedback_label.setText(
            'Incorrect.<br>'
            'Your answer: %s<br>'
            'Correct answer: %s' % (evaluation['typed_markup'], evaluation['expected_markup'])
        )
        self.feedback_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #b42318;")

    def _clear_feedback(self):
        self.feedback_label.setText('')
        self.feedback_label.setStyleSheet("font-size: 12px; font-weight: bold;")

    def _extract_text(self, value):
        value = self._extract_backside_html(value)
        # Convert answer HTML to plain text for basic comparison.
        # Strip style/script content first so CSS does not leak into feedback.
        cleaned = re.sub(r'<style[^>]*>.*?</style>', ' ', value or '', flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r'<script[^>]*>.*?</script>', ' ', cleaned, flags=re.IGNORECASE | re.DOTALL)
        no_tags = re.sub(r'<[^>]+>', ' ', cleaned)
        plain_text = html.unescape(no_tags)
        return ' '.join(plain_text.split())

    def _extract_backside_html(self, value):
        html_value = value or ''
        # Anki separator can be id="answer", id='answer', or id=answer.
        answer_sep = re.search(r'<hr[^>]*\bid\s*=\s*(["\']?)answer\1[^>]*>', html_value, flags=re.IGNORECASE)
        if answer_sep:
            return html_value[answer_sep.end():]

        # Fallback for templates that use plain <hr> without id.
        generic_sep = re.search(r'<hr\b[^>]*>', html_value, flags=re.IGNORECASE)
        if generic_sep:
            return html_value[generic_sep.end():]

        return html_value

    def _normalize_text(self, value):
        normalized = (value or '').strip().lower()
        normalized = re.sub(r'\s+', ' ', normalized)
        return normalized

    def _levenshtein_distance_max_one(self, left, right):
        # Fast distance check with early exit, only cares about 0/1/>1 edits.
        if abs(len(left) - len(right)) > 1:
            return 2

        i = 0
        j = 0
        edits = 0
        while i < len(left) and j < len(right):
            if left[i] == right[j]:
                i += 1
                j += 1
                continue

            edits += 1
            if edits > 1:
                return edits

            if len(left) == len(right):
                i += 1
                j += 1
            elif len(left) > len(right):
                i += 1
            else:
                j += 1

        if i < len(left) or j < len(right):
            edits += 1

        return edits

    def _highlight_diff(self, typed_word, expected_word):
        typed_html = []
        expected_html = []
        max_len = max(len(typed_word), len(expected_word))

        for idx in range(max_len):
            typed_char = typed_word[idx] if idx < len(typed_word) else ''
            expected_char = expected_word[idx] if idx < len(expected_word) else ''

            if typed_char == expected_char:
                if typed_char:
                    escaped = html.escape(typed_char)
                    typed_html.append(escaped)
                    expected_html.append(escaped)
            else:
                if typed_char:
                    typed_html.append('<span style="background:#ffd6d6;">%s</span>' % html.escape(typed_char))
                if expected_char:
                    expected_html.append('<span style="background:#d9fbe1;">%s</span>' % html.escape(expected_char))

        return ''.join(typed_html) or '-', ''.join(expected_html) or '-'

    def _evaluate_typed_answer(self, typed_answer, answer_html):
        typed_norm = self._normalize_text(typed_answer)
        answer_text = self._extract_text(answer_html)
        answer_norm = self._normalize_text(answer_text)

        result = {
            'is_correct': False,
            'accepted_with_one_error': False,
            'typed': typed_answer,
            'typed_markup': html.escape(typed_answer or '-'),
            'expected_markup': html.escape(answer_text[:120] or '-')
        }

        if not typed_norm or not answer_norm:
            return result

        if typed_norm == answer_norm:
            result['is_correct'] = True
            result['expected_markup'] = html.escape(answer_text)
            return result

        best_word = answer_norm
        best_distance = self._levenshtein_distance_max_one(typed_norm, answer_norm)

        # For single-word input, compare against individual answer words as well.
        if ' ' not in typed_norm:
            answer_words = re.findall(r'\w+', answer_norm)
            for answer_word in answer_words:
                distance = self._levenshtein_distance_max_one(typed_norm, answer_word)
                if distance < best_distance:
                    best_distance = distance
                    best_word = answer_word

        if best_distance == 0:
            result['is_correct'] = True
            typed_markup, expected_markup = self._highlight_diff(typed_norm, best_word)
            result['typed_markup'] = typed_markup
            result['expected_markup'] = expected_markup
            return result

        if best_distance == 1:
            result['is_correct'] = True
            result['accepted_with_one_error'] = True
            typed_markup, expected_markup = self._highlight_diff(typed_norm, best_word)
            result['typed_markup'] = typed_markup
            result['expected_markup'] = expected_markup
            return result

        typed_markup, expected_markup = self._highlight_diff(typed_norm, best_word)
        result['typed_markup'] = typed_markup
        result['expected_markup'] = expected_markup
        return result

    def toggle_typing_mode(self):
        self.typing_mode = not self.typing_mode
        self._apply_typing_toggle_ui()
        self.answer_input.clear()
        self.logger.debug('typing_mode toggled to %s' % self.typing_mode)

        # Refresh controls in whichever mode is currently displayed.
        if self.popup_window.isVisible():
            if self.pre_reveal_mode:
                self.show_show_button()
            else:
                self.show_question_button()
                if self.typing_mode:
                    self.answer_input.setFocus()

    def reset_card(self):
        self.card_view.setHtml(None)

    def prep_card(self):
        # Update card with 'Reveal card' html
        self.card_view.setHtml("""
                    <!doctype html>
                    <html>
                        <head></head>
                        <body>
                            <div style="margin: auto; text-align: center; line-height: 90vh; font-size: 60px;">🔔</div>
                        </body>
                    </html>
                """)

    def update_card(self, card):
        # TODO - Look into using existing AnkiWebView object to render duplicate card with full compatibility
        self.card_view.setHtml("""
                    <!doctype html>
                    <html class=" webkit chrome win js">
                        <head>
                            <title>main webview</title>
                            <style>
                                body { zoom: 1; background: #f0f0f0; direction: ltr; font-size:12px;font-family:"Segoe UI"; }
                                button { font-family:"Segoe UI"; }
                                :focus { outline: 1px solid #0078d7; }
                            </style>
                        </head>

                        <body class="card card2 isWin">
                            <div id="qa" style="opacity: 1;">
                                """ + card + """
                            </div>
                        </body>
                    </html>
                """)

    def pre_popup_validate(self):
        self.logger.info('pre_popup_validate...')
        # Get current deck from config
        current_deck = self.anki_utils.get_config()['deck']

        # Check that review is active and current deck is as expected (if not then start review)
        if not self.anki_utils.review_is_active() or current_deck != self.anki_utils.selected_deck():
            self.logger.info('Start review...')
            review_started = self.anki_utils.move_to_review_state(current_deck)
            self.logger.info('review_started: %s' % review_started)
            if not review_started:
                raise Exception('Failed to start review...')
            if review_started and not self.anki_utils.review_is_active():
                self.logger.info('No cards left to review')
                # TODO - Show popup saying no cards left, state that schedule is now off
                # TODO - Turn off schedule automatically

    def show_answer_popup(self):
        self.logger.info('show_answer_popup...')
        typed_answer = self.answer_input.text().strip()
        self.last_typed_answer = typed_answer
        self.popup_window.hide()
        self.pre_popup_validate()
        self.answer_input.clear()

        # TODO - Extra if this fails for some reason
        show_ans_result = self.anki_utils.show_answer()
        self.logger.debug('Show Answer Result: %s' % show_ans_result)

        # Collect card details (html, css, buttons)
        current_card = self.anki_utils.get_current_card()
        if self.current_card_id != current_card['card_id']:
            self.logger.info('Card has changed, show new card...')
            self.show_question_popup()
        else:
            self.cur_button_count = len(current_card['button_list'])
            if self.typing_mode and typed_answer:
                evaluation = self._evaluate_typed_answer(typed_answer, current_card['answer'])
                self._set_feedback(evaluation)
            else:
                self._clear_feedback()
            self.show_answer_buttons()
            self.update_card(current_card['answer'])

            # Show pop-up
            self.set_card_position()
            self.popup_window.show()

    def show_popup(self):
        self.logger.info('show_popup...')
        self._clear_feedback()
        # Enter pre reveal state based on user config
        if self.anki_utils.get_config()['click_to_reveal']:
            self.hide_card()
            self.prep_card()
            self.show_show_button()
            self.set_card_position()
            self.popup_window.show()
        else:
            self.show_question_popup()

    def show_question_popup(self):
        self.logger.info('show_question_popup...')
        self._clear_feedback()
        self.popup_window.hide()
        self.pre_popup_validate()
        show_q_result = self.anki_utils.show_question()
        self.logger.debug('Show Question Result: %s' % show_q_result)

        # Collect card details (html, css, buttons)
        current_card = self.anki_utils.get_current_card()
        self.current_card_id = current_card['card_id']
        self.logger.debug('Setting current card to %s' % current_card['card_id'])
        self.update_card(current_card['question'])
        self.show_question_button()

        # Show pop-up
        self.set_card_position()
        self.popup_window.show()

    def send_answer(self, ease_name):
        # TODO - Clean this up, not elegant at all
        if self.cur_button_count == 2:
            if ease_name == "Again":
                ease = 1
            elif ease_name == "Good":
                ease = 2
            else:
                raise Exception('Invalid ease used, expected [Again] or [Good] but got [%s]' % ease_name)
        elif self.cur_button_count == 3:
            if ease_name == "Again":
                ease = 1
            elif ease_name == "Good":
                ease = 2
            elif ease_name == "Easy":
                ease = 3
            else:
                raise Exception('Invalid ease used, expected [Again], [Good] or [Easy] but got [%s]' % ease_name)
        else:
            if ease_name == "Again":
                ease = 1
            elif ease_name == "Hard":
                ease = 2
            elif ease_name == "Good":
                ease = 3
            elif ease_name == "Easy":
                ease = 4
            else:
                raise Exception('Invalid ease used, expected '
                                '[Again], [Hard], [Good] or [Easy] but got [%s]' % ease_name)

        self.logger.debug('send_answer with ease_name [%s]' % ease_name)
        self.logger.debug('send_answer with ease [%s]' % ease)

        # Get current card and check it's the expected card
        current_card = self.anki_utils.get_current_card()
        if current_card['card_id'] == self.current_card_id:
            # Send the answer
            answer_result = self.anki_utils.answer_card(ease)
            self.logger.debug('answer_result: %s' % answer_result)
        else:
            # TODO - Handle this better, notify user?
            self.logger.warning('The card you tried to answer is no longer the card being reviewed...')

        self.hide_popup()

    def hide_popup(self):
        self.reset_card()
        self.popup_window.hide()

    def hide_card(self):
        self.hide_popup()
        current_deck = self.anki_utils.get_config()['deck']
        review_ended = self.anki_utils.move_to_overview_state(current_deck)
        self.logger.info('review_ended: %s' % review_ended)
