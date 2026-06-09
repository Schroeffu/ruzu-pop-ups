# Copyright 2020 Charles Henry
from aqt.webview import AnkiWebView
from PyQt6 import QtCore, QtGui
from aqt import Qt, QWidget, QGridLayout, QPushButton, QDialog, QHBoxLayout, QLineEdit, QLabel, QMenu
from ..anki_utils import AnkiUtils
import logging
import re
import html
import time
import math


class _MoveHandle(QPushButton):
    """Button that drags its target window while the left mouse button is held."""

    def __init__(self, window, on_moved=None, clamp=None):
        super().__init__()
        self._window = window
        self._on_moved = on_moved
        self._clamp = clamp
        self._drag_offset = None

    def _move_window(self, point):
        if self._clamp is not None:
            point = self._clamp(point)
        self._window.move(point)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._window.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (
            event.buttons() & QtCore.Qt.MouseButton.LeftButton
        ):
            self._move_window(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            event.button() == QtCore.Qt.MouseButton.LeftButton
            and self._drag_offset is not None
        ):
            self._drag_offset = None
            if self._on_moved is not None:
                self._on_moved()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class RuzuPopup(QDialog):

    def __init__(self, parent):
        self.parent = parent
        self.anki_utils = AnkiUtils()
        self.current_card_id = None
        self.cur_button_count = 0
        config = self.anki_utils.get_config()
        self.enable_self_typing = config.get('enable_self_typing', False)
        self.typing_mode = False  # Always start with typing mode OFF
        self.pre_reveal_mode = False
        self.last_typed_answer = ''
        self.skip_until = 0  # Epoch time until which pop-ups are skipped (in-memory only)
        self.window_position = None  # Session only; resets when Anki restarts.
        self.speed_mode = False  # Session only; immediately load next card after answering.
        self.skip_options = [1, 2, 3, 5, 10, 15, 30, 60, 120, 180]
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
        self.typing_toggle_btn = None
        self.enable_self_typing = config.get('enable_self_typing', False)
        if self.enable_self_typing:
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
        # Settings icon (top right corner of the card view)
        ###
        self.settings_btn = QPushButton()
        self.settings_btn.setFixedSize(26, 26)
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setIcon(self._build_gear_icon())
        self.settings_btn.setIconSize(QtCore.QSize(18, 18))
        self.settings_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setStyleSheet(
            "QPushButton { border: none; background: rgba(0, 0, 0, 0.05);"
            " border-radius: 13px; }"
            " QPushButton:hover { background: rgba(0, 0, 0, 0.15); }"
        )
        self.settings_btn.clicked.connect(lambda _: self._show_settings_menu())

        ###
        # Move handle (drag the pop-up while left mouse button is held)
        ###
        self.move_btn = _MoveHandle(
            self.popup_window,
            on_moved=self._save_window_position,
            clamp=self._clamp_to_screens,
        )
        self.move_btn.setFixedSize(26, 26)
        self.move_btn.setToolTip("Move")
        self.move_btn.setIcon(self._build_move_icon())
        self.move_btn.setIconSize(QtCore.QSize(18, 18))
        self.move_btn.setCursor(QtCore.Qt.CursorShape.SizeAllCursor)
        self.move_btn.setStyleSheet(
            "QPushButton { border: none; background: rgba(0, 0, 0, 0.05);"
            " border-radius: 13px; }"
            " QPushButton:hover { background: rgba(0, 0, 0, 0.15); }"
        )

        ###
        # Speed Mode icon (instantly load the next card after answering)
        ###
        self.speed_btn = QPushButton()
        self.speed_btn.setFixedSize(26, 26)
        self.speed_btn.setIconSize(QtCore.QSize(18, 18))
        self.speed_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.speed_btn.clicked.connect(lambda _: self.toggle_speed_mode())
        self._apply_speed_toggle_ui()

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
        parent.top_btn_grid = self.top_btn_grid = QHBoxLayout()
        self.top_btn_grid.setContentsMargins(0, 4, 4, 0)
        self.top_btn_grid.setSpacing(4)
        self.top_btn_grid.addWidget(self.move_btn)
        self.top_btn_grid.addWidget(self.speed_btn)
        self.top_btn_grid.addWidget(self.settings_btn)
        self.grid.addLayout(
            self.top_btn_grid, 0, 0,
            QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignRight
        )
        self.grid.addLayout(self.bottom_grid, 1, 0)
        self.grid.addWidget(self.feedback_label, 2, 0)
        self.popup_window.setLayout(self.grid)

        # Timer used to defer the Speed Mode reload by one event-loop turn. Right
        # after answering, Anki has not yet advanced to the next card, so we must
        # yield to the event loop before re-rendering. The timer is parented to
        # popup_window (a real QObject) so it fires reliably.
        #
        # IMPORTANT: the timeout is connected via a lambda, NOT directly to
        # self._speed_reload. RuzuPopup derives from QDialog but never calls
        # super().__init__(), so it is not an initialised QObject. If a bound
        # method of such an object is used as a slot, PyQt treats it as a slot on
        # an (invalid) QObject receiver and Qt silently never delivers the
        # signal. A lambda's __self__ is a plain Python object, so the call goes
        # through normally (this is why the answer buttons, which also use
        # lambdas, work).
        self._speed_timer = QtCore.QTimer(self.popup_window)
        self._speed_timer.setSingleShot(True)
        self._speed_timer.timeout.connect(lambda: self._speed_reload())
        # Counts how many times _speed_reload has waited for Anki to advance to
        # the next card (used to cap the polling so it can never loop forever).
        self._speed_retries = 0

    def set_card_position(self):
        # If the user has dragged the pop-up before in this session, restore it.
        if isinstance(self.window_position, QtCore.QPoint):
            point = self._clamp_to_screens(self.window_position)
            self.popup_window.move(point)
            return

        # Default: move to bottom right of screen
        # https://stackoverflow.com/questions/28322073/move-qmessagebox-to-bottom-right-corner-of-the-screen
        # https://forum.qt.io/topic/134570/qapplication-desktop-screengeometry-not-work-in-qt6
        screen_geometry = self.parent.app.primaryScreen().availableGeometry()
        screen_geo = screen_geometry.bottomRight()
        msg_geo = self.popup_window.frameGeometry()
        msg_geo.moveBottomRight(screen_geo)
        self.popup_window.move(msg_geo.topLeft())

    def _clamp_to_screens(self, point):
        # Keep the whole window inside the visible desktop area so it can never
        # be dragged (or restored) off-screen and become unreachable.
        app = self.parent.app
        screen = app.screenAt(point)
        if screen is None:
            screen = (
                self.popup_window.screen()
                or app.primaryScreen()
            )
        area = screen.availableGeometry()
        win = self.popup_window.frameGeometry()

        max_x = area.right() - win.width() + 1
        max_y = area.bottom() - win.height() + 1
        # If the window is larger than the screen, prefer showing the top-left.
        x = min(max(point.x(), area.left()), max(max_x, area.left()))
        y = min(max(point.y(), area.top()), max(max_y, area.top()))
        return QtCore.QPoint(x, y)

    def _save_window_position(self):
        pos = self.popup_window.pos()
        self.window_position = QtCore.QPoint(pos.x(), pos.y())
        self.logger.info('Saved session pop-up position to (%s, %s)' % (pos.x(), pos.y()))

    def _build_move_icon(self):
        size = 36
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor(70, 70, 70))
        pen.setWidth(2)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(QtCore.Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QtGui.QBrush(QtGui.QColor(70, 70, 70)))

        c = size / 2.0
        arm = size * 0.30   # length of each arm from the centre
        head = size * 0.10  # half-width / depth of each arrowhead

        # Cross strokes.
        painter.drawLine(QtCore.QPointF(c, c - arm), QtCore.QPointF(c, c + arm))
        painter.drawLine(QtCore.QPointF(c - arm, c), QtCore.QPointF(c + arm, c))

        def triangle(tip, left, right):
            path = QtGui.QPainterPath()
            path.moveTo(tip)
            path.lineTo(left)
            path.lineTo(right)
            path.closeSubpath()
            painter.drawPath(path)

        # Up / down / left / right arrowheads.
        triangle(QtCore.QPointF(c, c - arm - head),
                 QtCore.QPointF(c - head, c - arm),
                 QtCore.QPointF(c + head, c - arm))
        triangle(QtCore.QPointF(c, c + arm + head),
                 QtCore.QPointF(c - head, c + arm),
                 QtCore.QPointF(c + head, c + arm))
        triangle(QtCore.QPointF(c - arm - head, c),
                 QtCore.QPointF(c - arm, c - head),
                 QtCore.QPointF(c - arm, c + head))
        triangle(QtCore.QPointF(c + arm + head, c),
                 QtCore.QPointF(c + arm, c - head),
                 QtCore.QPointF(c + arm, c + head))
        painter.end()

        return QtGui.QIcon(pixmap)

    def _build_speed_icon(self, active):
        size = 36
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        colour = QtGui.QColor(245, 158, 11) if active else QtGui.QColor(70, 70, 70)
        painter.setBrush(QtGui.QBrush(colour))

        # A simple lightning bolt polygon (scaled to the 36x36 canvas).
        points = [
            (21, 3),
            (9, 20),
            (17, 20),
            (15, 33),
            (27, 16),
            (19, 16),
        ]
        path = QtGui.QPainterPath()
        path.moveTo(points[0][0], points[0][1])
        for x, y in points[1:]:
            path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)
        painter.end()

        return QtGui.QIcon(pixmap)

    def _build_gear_icon(self):
        size = 36
        pixmap = QtGui.QPixmap(size, size)
        pixmap.fill(QtCore.Qt.GlobalColor.transparent)

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(QtGui.QColor(70, 70, 70)))

        center = size / 2.0
        outer_radius = size * 0.42
        inner_radius = size * 0.30
        teeth = 8

        # Build a cog shape by alternating between outer and inner radius.
        path = QtGui.QPainterPath()
        steps = teeth * 2
        for i in range(steps + 1):
            angle = (math.pi * 2.0 * i) / steps
            radius = outer_radius if i % 2 == 0 else inner_radius
            x = center + radius * math.cos(angle)
            y = center + radius * math.sin(angle)
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        path.closeSubpath()
        painter.drawPath(path)

        # Punch out the centre hole so it reads as a gear.
        hole_radius = size * 0.14
        painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Clear)
        painter.setBrush(QtGui.QBrush(QtCore.Qt.GlobalColor.black))
        painter.drawEllipse(QtCore.QPointF(center, center), hole_radius, hole_radius)
        painter.end()

        return QtGui.QIcon(pixmap)

    def _format_skip_label(self, minutes):
        if minutes < 60:
            return "%d minute%s" % (minutes, "" if minutes == 1 else "s")
        hours = minutes // 60
        return "%d hour%s" % (hours, "" if hours == 1 else "s")

    def _show_settings_menu(self):
        menu = QMenu(self.popup_window)
        skip_menu = menu.addMenu("Skip pop-ups for...")
        for minutes in self.skip_options:
            action = skip_menu.addAction(self._format_skip_label(minutes))
            action.triggered.connect(
                lambda checked=False, mins=minutes: self.skip_popups_for(mins)
            )
        if time.time() < self.skip_until:
            remaining = int((self.skip_until - time.time()) / 60) + 1
            resume = menu.addAction("Resume pop-ups now (~%d min left)" % remaining)
            resume.triggered.connect(lambda checked=False: self.resume_popups())
        menu.exec(self.settings_btn.mapToGlobal(self.settings_btn.rect().bottomLeft()))

    def skip_popups_for(self, minutes):
        self.skip_until = time.time() + minutes * 60
        self.logger.info(
            'Skipping pop-ups for %d minutes (until %s)' % (minutes, time.ctime(self.skip_until))
        )
        # Dismiss the current pop-up if it is showing.
        self.hide_popup()

    def resume_popups(self):
        self.skip_until = 0
        self.logger.info('Skip cancelled, pop-ups resumed')

    def show_show_button(self):
        self.pre_reveal_mode = True
        self._clear_bottom_controls()
        if self.typing_mode:
            self.bottom_grid.addWidget(self.answer_input)
            self.answer_input.setFocus()
        self.bottom_grid.addWidget(self.btn[5])
        if self.typing_toggle_btn:
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
        if self.typing_toggle_btn:
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
        if self.typing_toggle_btn:
            self.bottom_grid_2.addWidget(self.typing_toggle_btn)
        self.bottom_grid_2.addWidget(self.answer_input)

    def _apply_speed_toggle_ui(self):
        active = self.speed_mode
        self.speed_btn.setIcon(self._build_speed_icon(active))
        if active:
            self.speed_btn.setToolTip("Speed Mode: ON")
            self.speed_btn.setStyleSheet(
                "QPushButton { border: none; background: rgba(245, 158, 11, 0.25);"
                " border-radius: 13px; }"
                " QPushButton:hover { background: rgba(245, 158, 11, 0.40); }"
            )
        else:
            self.speed_btn.setToolTip("Speed Mode: OFF")
            self.speed_btn.setStyleSheet(
                "QPushButton { border: none; background: rgba(0, 0, 0, 0.05);"
                " border-radius: 13px; }"
                " QPushButton:hover { background: rgba(0, 0, 0, 0.15); }"
            )

    def toggle_speed_mode(self):
        self.speed_mode = not self.speed_mode
        self._apply_speed_toggle_ui()
        self.logger.debug('speed_mode toggled to %s' % self.speed_mode)

    def _apply_typing_toggle_ui(self):
        if not self.typing_toggle_btn:
            return
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
            self._focus_popup()

    def _focus_popup(self):
        # Keep the frameless, always-on-top popup visually on top. Button clicks
        # no longer depend on the window being active (see _PopupWindow), so we
        # only raise it here and avoid aggressively grabbing activation, which
        # could otherwise interfere with the click currently being processed.
        if self.popup_window.isVisible():
            self.popup_window.raise_()

    def _speed_reload(self):
        # Load the next card for Speed Mode. Right after answering, Anki may not
        # have advanced to the next card yet. If we re-rendered immediately the
        # "skip rerender" guard in show_question_popup() would still see the old
        # card and abort, leaving the pop-up stuck on the answered card. So we
        # poll: if Anki still reports the just-answered card, wait a moment and
        # try again (capped so it can never loop forever).
        if self.current_card_id is not None and self.anki_utils.review_is_active():
            try:
                current_card = self.anki_utils.get_current_card()
            except Exception:
                current_card = None
            if current_card is not None and current_card['card_id'] == self.current_card_id:
                if self._speed_retries < 40:  # ~2s worth of 50ms polls
                    self._speed_retries += 1
                    self._speed_timer.start(50)
                    return
        self._speed_retries = 0

        # Anki has advanced (or we gave up waiting). Render the next card. Unlike
        # show_popup() this deliberately ignores the skip window and the "user is
        # actively reviewing" guard, because right after answering a card Anki's
        # main window is focused and those guards would otherwise cancel reload.
        self._clear_feedback()
        if self.anki_utils.get_config()['click_to_reveal']:
            self.hide_card()
            self.prep_card()
            self.show_show_button()
            self.set_card_position()
            self.popup_window.show()
            self._focus_popup()
        else:
            self.show_question_popup()

    def show_popup(self):
        self.logger.info('show_popup...')
        # Honour one-off skip window (in-memory, resets on Anki restart).
        if time.time() < self.skip_until:
            self.logger.info('Pop-up skipped, skip active until %s' % time.ctime(self.skip_until))
            return
        # Don't interrupt while the user is actively studying a deck in Anki.
        if self.anki_utils.user_is_actively_reviewing():
            self.logger.info('Pop-up skipped, user is actively reviewing in Anki')
            return
        self._clear_feedback()
        # Enter pre reveal state based on user config
        if self.anki_utils.get_config()['click_to_reveal']:
            self.hide_card()
            self.prep_card()
            self.show_show_button()
            self.set_card_position()
            self.popup_window.show()
            self._focus_popup()
        else:
            self.show_question_popup()

    def show_question_popup(self):
        self.logger.info('show_question_popup...')

        # Skip re-render if popup is already visible with the same card.
        # Only safe to check when a review is actually active, otherwise
        # get_current_card() raises (e.g. after a click-to-reveal cycle).
        if (self.popup_window.isVisible() and self.current_card_id is not None
                and self.anki_utils.review_is_active()):
            current_card = self.anki_utils.get_current_card()
            if current_card['card_id'] == self.current_card_id:
                self.logger.debug('Card already displayed, skipping rerender')
                return

        self._clear_feedback()
        # Hide first so the subsequent show() re-activates the window. On Windows
        # re-showing a hidden top-level window makes it the foreground/active
        # window, which is what lets a single click hit the answer buttons.
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
        self._focus_popup()
        # Restore focus to answer input if typing mode is active. Typing needs
        # real keyboard focus, so activate the window explicitly here (button
        # clicks no longer rely on activation, but text input still does).
        if self.typing_mode:
            self.popup_window.activateWindow()
            self.answer_input.setFocus()

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

        # In Speed Mode, load the next card automatically. The reload is deferred
        # via a timer so Anki has a chance to advance to the next card first;
        # _speed_reload() then polls until the new card is actually available.
        if self.speed_mode:
            self._speed_retries = 0
            self._speed_timer.start(50)
        else:
            self.hide_popup()

    def hide_popup(self):
        self.reset_card()
        self.popup_window.hide()

    def hide_card(self):
        self.hide_popup()
        current_deck = self.anki_utils.get_config()['deck']
        review_ended = self.anki_utils.move_to_overview_state(current_deck)
        self.logger.info('review_ended: %s' % review_ended)
