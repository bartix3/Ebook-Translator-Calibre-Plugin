import time
import traceback
from types import MethodType

from calibre.gui2.dialogs.message_box import JobError

from .config import get_config
from .cache import Paragraph, get_cache
from .translation import get_engine_class, get_translator, get_translation
from .element import get_ebook_elements, get_element_handler
from .convertion import ebook_pages
from .components import (
    EngineList, layout_info, SourceLang, TargetLang, InputFormat, OutputFormat,
    AlertMessage, AdvancedTranslationTable)


try:
    from qt.core import (
        Qt, QObject, QDialog, QGroupBox, QWidget, QVBoxLayout, QHBoxLayout,
        QPlainTextEdit, QPushButton, QSplitter, QLabel, QThread, QLineEdit,
        QGridLayout, QProgressBar, pyqtSignal, pyqtSlot, QPixmap, QEvent,
        QStackedWidget, QSpacerItem, QTextCursor, QSettings, QTabWidget)
except ImportError:
    from PyQt5.Qt import (
        Qt, QObject, QDialog, QGroupBox, QWidget, QVBoxLayout, QHBoxLayout,
        QPlainTextEdit, QPushButton, QSplitter, QLabel, QThread, QLineEdit,
        QGridLayout, QProgressBar, pyqtSignal, pyqtSlot, QPixmap, QEvent,
        QStackedWidget, QSpacerItem, QTextCursor, QSettings, QTabWidget)

load_translations()


class StatusWorker(QObject):
    start = pyqtSignal((str,), (str, object))
    show = pyqtSignal(str)

    def __init__(self):
        QObject.__init__(self)
        self.start[str].connect(self.show_message)
        self.start[str, object].connect(self.show_message)

    @pyqtSlot(str)
    @pyqtSlot(str, object)
    def show_message(self, message, callback=None):
        self.show.emit(message)
        time.sleep(1)
        self.show.emit('')
        callback and callback()


class PreparationWorker(QObject):
    start = pyqtSignal()
    progress = pyqtSignal(int)
    progress_message = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, ebook, engine_class):
        QObject.__init__(self)
        self.ebook = ebook
        self.engine_class = engine_class
        self.start.connect(self.prepare_ebook_data)

    @pyqtSlot()
    def prepare_ebook_data(self):
        input_path = self.ebook.get_input_path()
        target_lang = self.ebook.target_lang
        element_handler = get_element_handler(target_lang)
        cache_id = (
            input_path + self.engine_class.name + target_lang
            + str(element_handler.get_merge_length()))
        cache = get_cache(cache_id)

        if cache.is_fresh() or not cache.is_persistence():
            a = time.time()
            # --------------------------
            self.progress_message.emit(_('Extracting ebook content...'))
            elements = get_ebook_elements(
                ebook_pages(input_path), self.engine_class.placeholder)
            self.progress.emit(30)
            b = time.time()
            print('extract: ', b - a)
            if self.cancel():
                return
            # --------------------------
            self.progress_message.emit(_('Filter original content...'))
            original_group = element_handler.prepare_original(elements)
            self.progress.emit(80)
            c = time.time()
            print('filter: ', c - b)
            if self.cancel():
                return
            # --------------------------
            self.progress_message.emit(_('Preparing user interface...'))
            cache.save(original_group)
            self.progress.emit(100)
            d = time.time()
            print('cache: ', d - c)
            if self.cancel():
                return

        self.finished.emit(cache_id)

    def cancel(self):
        return self.thread().isInterruptionRequested()


class TranslationWorker(QObject):
    start = pyqtSignal()
    finished = pyqtSignal(bool)
    translate = pyqtSignal(list, bool)
    logging = pyqtSignal(str)
    error = pyqtSignal(str, str, str)
    streaming = pyqtSignal(object)
    callback = pyqtSignal(object)

    def __init__(self, ebook, engine_class):
        QObject.__init__(self)
        self.source_lang = ebook.source_lang
        self.target_lang = ebook.target_lang
        self.engine_class = engine_class

        self.cancelled = False
        self.translate.connect(self.translate_paragraphs)
        self.finished.connect(lambda: self.set_cancelled(False))

    def set_source_lang(self, lang):
        self.source_lang = lang

    def set_target_lang(self, lang):
        self.target_lang = lang

    def set_engine_class(self, engine_class):
        self.engine_class = engine_class

    def set_cancelled(self, cancelled):
        self.cancelled = cancelled

    def cancel_request(self):
        return self.cancelled

    @pyqtSlot(list, bool)
    def translate_paragraphs(self, paragraphs=[], fresh=False):
        self.start.emit()
        translator = get_translator(self.engine_class)
        translator.set_source_lang(self.source_lang)
        translator.set_target_lang(self.target_lang)
        translation = get_translation(translator)
        translation.set_fresh(fresh)
        translation.set_logging(self.logging.emit)
        translation.set_streaming(self.streaming.emit)
        translation.set_callback(self.callback.emit)
        translation.set_cancel_request(self.cancel_request)
        try:
            translation.handle(paragraphs)
            self.finished.emit(not self.cancel_request())
        except Exception as e:
            reason = traceback.format_exc()
            self.logging.emit(reason)
            self.streaming.emit('')
            self.streaming.emit(str(e))
            self.error.emit(_('Translation Failed'), str(e), reason)
            self.finished.emit(False)
        self.cancelled = False


class CreateTranslationProject(QDialog):
    start_translation = pyqtSignal()

    def __init__(self, parent, ebook):
        QDialog.__init__(self, parent)
        self.ebook = ebook

        layout = QVBoxLayout(self)
        self.choose_format = self.layout_format()

        self.start_button = QPushButton(_('Start'))
        # self.start_button.setStyleSheet(
        #     'padding:0;height:48;font-size:20px;color:royalblue;'
        #     'text-transform:uppercase;')
        self.start_button.clicked.connect(self.show_advanced)

        layout.addWidget(self.choose_format)
        layout.addWidget(self.start_button)

    def layout_format(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        input_group = QGroupBox(_('Input Format'))
        input_layout = QGridLayout(input_group)
        input_format = InputFormat(self.ebook.files.keys())
        input_format.setFixedWidth(150)
        input_layout.addWidget(input_format)

        def change_input_format(format):
            self.ebook.input_format = format
        change_input_format(input_format.currentText())
        input_format.currentTextChanged.connect(change_input_format)

        target_group = QGroupBox(_('Target Language'))
        target_layout = QVBoxLayout(target_group)
        target_lang = TargetLang()
        target_lang.setFixedWidth(150)
        target_layout.addWidget(target_lang)

        engine_class = get_engine_class()
        target_lang.refresh.emit(
            engine_class.lang_codes.get('target'),
            engine_class.config.get('target_lang'))
        self.ebook.set_target_lang(target_lang.currentText())
        target_lang.currentTextChanged.connect(self.ebook.set_target_lang)

        layout.addWidget(input_group)
        layout.addWidget(target_group)

        return widget

    @pyqtSlot()
    def show_advanced(self):
        self.done(0)
        self.start_translation.emit()


class AdvancedTranslation(QDialog):
    ui_setting = QSettings()

    raw_text = pyqtSignal(str)
    original_text = pyqtSignal(str)
    translation_text = pyqtSignal((), (str,))
    progress_bar = pyqtSignal()

    preparation_thread = QThread()
    trans_thread = QThread()
    status_thread = QThread()

    def __init__(self, parent, icon, ebook, worker):
        QDialog.__init__(self, parent)
        self.api = parent.current_db.new_api
        self.icon = icon
        self.ebook = ebook
        self.worker = worker
        self.config = get_config()
        self.alert = AlertMessage(self)
        self.error = JobError(self)
        self.current_engine = get_engine_class()
        self.cache = None

        self.on_working = False
        self.prgress_step = 0
        self.translate_all = False

        self.status_worker = StatusWorker()
        self.status_worker.moveToThread(self.status_thread)
        self.status_thread.finished.connect(self.status_worker.deleteLater)
        self.status_thread.start()

        self.trans_worker = TranslationWorker(self.ebook, self.current_engine)
        self.trans_worker.moveToThread(self.trans_thread)
        self.trans_thread.finished.connect(self.trans_worker.deleteLater)
        self.trans_thread.start()

        self.preparation_worker = PreparationWorker(
            self.ebook, self.current_engine)
        self.preparation_worker.moveToThread(self.preparation_thread)
        self.preparation_thread.finished.connect(
            self.preparation_worker.deleteLater)
        self.preparation_thread.start()

        layout = QVBoxLayout(self)

        self.waiting = self.layout_progress()

        self.stack = QStackedWidget()
        self.stack.addWidget(self.waiting)
        layout.addWidget(self.stack)
        layout.addWidget(layout_info())

        def working_status():
            self.on_working = True
        self.trans_worker.start.connect(working_status)

        def working_finished(success):
            if self.translate_all and success:
                self.alert.pop(_('Translation completed.'))
            self.translate_all = False
            self.on_working = False
        self.trans_worker.finished.connect(working_finished)

        self.trans_worker.error.connect(
            lambda title, reason, detail: self.error.show_error(
                title, _('Failed') + ': ' + reason, det_msg=detail))

        def prepare_table_layout(cache_id):
            self.cache = get_cache(cache_id)
            paragraphs = self.cache.all_paragraphs()
            if len(paragraphs) < 1:
                self.alert.pop(
                    _('There is no content that needs to be translated.'),
                    'warning')
                self.done(0)
                return
            self.table = AdvancedTranslationTable(self, paragraphs)
            self.panel = self.layout_panel()
            self.stack.addWidget(self.panel)
            self.stack.setCurrentWidget(self.panel)
        self.preparation_worker.finished.connect(prepare_table_layout)
        self.preparation_worker.start.emit()

    def layout_progress(self):
        widget = QWidget()
        layout = QGridLayout(widget)

        try:
            cover_image = self.api.cover(self.ebook.id, as_pixmap=True)
        except Exception:
            cover_image = QPixmap(self.api.cover(self.ebook.id, as_image=True))
        if cover_image.isNull():
            cover_image = QPixmap(I('default_cover.png'))
        mode = getattr(Qt.TransformationMode, 'SmoothTransformation', None) \
            or Qt.SmoothTransformation
        cover_image = cover_image.scaledToHeight(480, mode)

        cover = QLabel()
        cover.setAlignment(Qt.AlignCenter)
        cover.setPixmap(cover_image)

        progress_bar = QProgressBar()
        progress_bar.setFormat('')
        progress_bar.setValue(0)
        # progress_bar.setFixedWidth(300)
        # progress_bar.setMaximum(0)
        # progress_bar.setMinimum(0)
        self.preparation_worker.progress.connect(progress_bar.setValue)

        label = QLabel(_('Reading ebook data, please wait...'))
        label.setAlignment(Qt.AlignCenter)
        self.preparation_worker.progress_message.connect(label.setText)

        layout.addItem(QSpacerItem(0, 0), 0, 0, 1, 3)
        layout.addWidget(cover, 1, 1)
        layout.addItem(QSpacerItem(0, 30), 2, 0, 1, 3)
        layout.addWidget(progress_bar, 3, 1)
        layout.addWidget(label, 4, 1)
        layout.addItem(QSpacerItem(0, 0), 5, 0, 1, 3)
        layout.setRowStretch(0, 1)
        layout.setRowStretch(5, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(2, 1)

        return widget

    def layout_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        tabs = QTabWidget()
        tabs.addTab(self.layout_review(), _('Review'))
        tabs.addTab(self.layout_log(), _('Log'))
        tabs.setStyleSheet('QTabBar::tab {min-width:120px;}')

        self.trans_worker.start.connect(
            lambda: (self.translate_all or self.table.selected_count() > 1)
            and tabs.setCurrentIndex(1))
        self.trans_worker.finished.connect(
            lambda success: success and self.translate_all
            and tabs.setCurrentIndex(0))

        splitter = QSplitter()
        splitter.addWidget(self.layout_table())
        splitter.addWidget(tabs)

        layout.addWidget(self.layout_control())
        layout.addWidget(splitter, 1)

        return widget

    def layout_table(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        progress_bar = QProgressBar()
        progress_bar.setMaximum(10000)
        progress_bar.setVisible(False)

        def write_progress():
            value = progress_bar.value() + self.prgress_step
            if value > progress_bar.maximum():
                value = progress_bar.maximum()
            progress_bar.setValue(value)
        self.progress_bar.connect(write_progress)

        layout.addWidget(self.table, 1)
        layout.addWidget(progress_bar)
        layout.addWidget(self.layout_table_control())

        def working_start():
            if self.translate_all:
                progress_bar.setValue(0)
                progress_bar.setVisible(True)
        self.trans_worker.start.connect(working_start)

        def working_finished(success):
            progress_bar.setVisible(False)
        self.trans_worker.finished.connect(working_finished)

        return widget

    def layout_table_control(self):
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 0, 0, 0)

        translate_all = QPushButton('  %s  ' % _('Translate All'))
        translate_selected = QPushButton('  %s  ' % _('Translate Selected'))
        delete_button = QPushButton(_('Delete'))

        translate_all.clicked.connect(self.translate_all_paragraphs)
        translate_selected.clicked.connect(self.translate_selected_paragraph)
        self.table.itemSelectionChanged.connect(
            lambda: translate_selected.setDisabled(
                self.table.selected_count() < 1))

        delete_button.clicked.connect(self.table.delete_by_rows)
        self.table.itemSelectionChanged.connect(
            lambda: delete_button.setDisabled(
                self.table.selected_count() < 1))

        action_layout.addWidget(delete_button)
        action_layout.addStretch(1)
        action_layout.addWidget(translate_all)
        action_layout.addWidget(translate_selected)

        stop_widget = QWidget()
        stop_layout = QHBoxLayout(stop_widget)
        stop_layout.setContentsMargins(0, 0, 0, 0)
        # stop_layout.addStretch(1)
        stop_button = QPushButton(_('Stop'))
        stop_layout.addWidget(stop_button)

        def terminate_translation():
            if self.terminate_translation():
                stop_button.setDisabled(True)
                stop_button.setText(_('Stopping...'))
        stop_button.clicked.connect(terminate_translation)

        def terminate_finished():
            stop_button.setDisabled(False)
            stop_button.setText(_('Stop'))
            paragraph = self.table.current_paragraph()
            self.translation_text[str].emit(paragraph.translation)
        self.trans_worker.finished.connect(terminate_finished)

        stack = QStackedWidget()
        stack.addWidget(action_widget)
        stack.addWidget(stop_widget)

        def working_start():
            stack.setCurrentWidget(stop_widget)
            action_widget.setDisabled(True)
        self.trans_worker.start.connect(working_start)

        def working_finished(success):
            stack.setCurrentWidget(action_widget)
            action_widget.setDisabled(False)
        self.trans_worker.finished.connect(working_finished)

        return stack

    def layout_control(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        engine_group = QGroupBox(_('Translation Engine'))
        engine_layout = QVBoxLayout(engine_group)
        engine_list = EngineList(self.current_engine.name)
        engine_list.setFixedWidth(150)
        engine_layout.addWidget(engine_list)

        source_group = QGroupBox(_('Source Language'))
        source_layout = QVBoxLayout(source_group)
        source_lang = SourceLang()
        source_lang.setFixedWidth(150)
        source_layout.addWidget(source_lang)

        target_group = QGroupBox(_('Target Language'))
        target_layout = QVBoxLayout(target_group)
        target_lang = TargetLang()
        target_lang.setFixedWidth(150)
        target_layout.addWidget(target_lang)

        save_group = QGroupBox(_('Output Ebook'))
        save_layout = QHBoxLayout(save_group)
        save_ebook = QPushButton(_('Output'))
        ebook_title = QLineEdit()
        ebook_title.setText(self.ebook.title)
        ebook_title.setCursorPosition(0)
        output_format = OutputFormat()
        output_format.setFixedWidth(150)
        save_layout.addWidget(QLabel(_('Title')))
        save_layout.addWidget(ebook_title, 1)
        save_layout.addWidget(output_format)
        save_layout.addWidget(save_ebook)

        ebook_title.textChanged.connect(self.ebook.set_title)

        layout.addWidget(engine_group)
        layout.addWidget(source_group)
        layout.addWidget(target_group)
        layout.addWidget(save_group)

        source_lang.currentTextChanged.connect(
            self.trans_worker.set_source_lang)
        target_lang.currentTextChanged.connect(
            self.trans_worker.set_target_lang)

        def refresh_languages():
            source_lang.refresh.emit(
                self.current_engine.lang_codes.get('source'),
                self.current_engine.config.get('source_lang'),
                not self.current_engine.is_custom())
            target_lang.refresh.emit(
                self.current_engine.lang_codes.get('target'),
                self.ebook.target_lang)
        refresh_languages()
        self.ebook.set_source_lang(source_lang.currentText())

        def choose_engine(index):
            engine_name = engine_list.itemData(index)
            self.current_engine = get_engine_class(engine_name)
            self.trans_worker.set_engine_class(self.current_engine)
            refresh_languages()
        engine_list.currentIndexChanged.connect(choose_engine)

        def change_output_format(format):
            self.ebook.output_format = format
        change_output_format(output_format.currentText())
        output_format.currentTextChanged.connect(change_output_format)

        def output_ebook():
            if len(self.table.findItems(_('Translated'), Qt.MatchExactly)) < 1:
                self.alert.pop('The ebook has not been translated yet.')
                return
            self.worker.translate_ebook(self.ebook, cache_only=True)
            self.done(1)
        save_ebook.clicked.connect(output_ebook)

        def working_start():
            self.translate_all and widget.setVisible(False)
            widget.setDisabled(True)
        self.trans_worker.start.connect(working_start)

        def working_finished(success):
            widget.setVisible(True)
            widget.setDisabled(False)
        self.trans_worker.finished.connect(working_finished)

        return widget

    def layout_review(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        splitter = QSplitter(Qt.Vertical)
        splitter.setContentsMargins(0, 0, 0, 0)
        raw_text = QPlainTextEdit()
        raw_text.setReadOnly(True)
        original_text = QPlainTextEdit()
        original_text.setReadOnly(True)
        translation_text = QPlainTextEdit()
        translation_text.setPlaceholderText(_('No translation yet'))
        splitter.addWidget(raw_text)
        splitter.addWidget(original_text)
        splitter.addWidget(translation_text)
        splitter.setSizes([0, 1, 1])

        translation_text.cursorPositionChanged.connect(
            translation_text.ensureCursorVisible)

        self.raw_text.connect(raw_text.setPlainText)
        self.original_text.connect(original_text.setPlainText)
        self.translation_text.connect(translation_text.clear)
        self.translation_text[str].connect(translation_text.setPlainText)
        self.trans_worker.start.connect(
            lambda: translation_text.setReadOnly(False))
        self.trans_worker.finished.connect(
            lambda success: translation_text.setReadOnly(False))

        default_flag = translation_text.textInteractionFlags()

        def disable_translation_text():
            if self.on_working:
                translation_text.setTextInteractionFlags(Qt.TextEditable)
                end = getattr(QTextCursor.MoveOperation, 'End', None) or \
                    QTextCursor.End
                translation_text.moveCursor(end)
            else:
                translation_text.setTextInteractionFlags(default_flag)
        translation_text.cursorPositionChanged.connect(
            disable_translation_text)

        def auto_open_close_splitter():
            size = 0 if splitter.sizes()[0] > 0 else 1
            splitter.setSizes([size, 1, 1])
        self.install_widget_event(
            splitter, splitter.handle(1), QEvent.MouseButtonDblClick,
            auto_open_close_splitter)

        self.table.itemDoubleClicked.connect(
            lambda item: auto_open_close_splitter())

        control = QWidget()
        control.setVisible(False)
        controle_layout = QHBoxLayout(control)
        controle_layout.setContentsMargins(0, 0, 0, 0)

        save_status = QLabel()
        save_button = QPushButton(_('Save'))

        controle_layout.addWidget(save_status)
        controle_layout.addStretch(1)
        controle_layout.addWidget(save_button)

        layout.addWidget(splitter)
        layout.addWidget(control)

        def change_selected_item():
            rows = self.table.get_selected_rows()
            if not self.on_working and len(rows) > 0:
                paragraph = self.table.paragraph(rows.pop(0))
                self.raw_text.emit(paragraph.raw)
                self.original_text.emit(paragraph.original)
                self.translation_text[str].emit(paragraph.translation)
        self.table.itemSelectionChanged.connect(change_selected_item)
        self.table.setCurrentItem(self.table.item(0, 0))

        def translation_callback(paragraph):
            row = paragraph.row
            self.table.row.emit(row)
            self.raw_text.emit(paragraph.raw)
            self.original_text.emit(paragraph.original)
            self.translation_text[str].emit(paragraph.translation)
            self.cache.update_paragraph(paragraph)
            self.progress_bar.emit()
        self.trans_worker.callback.connect(translation_callback)

        def streaming_translation(data):
            if data == '':
                self.translation_text.emit()
            elif isinstance(data, Paragraph):
                self.table.setCurrentItem(self.table.item(data.row, 0))
            else:
                translation_text.insertPlainText(data)
        self.trans_worker.streaming.connect(streaming_translation)

        def modify_translation():
            if not self.on_working:
                paragraph = self.table.current_paragraph()
                translation = translation_text.toPlainText()
                control.setVisible(
                    bool(translation) and translation != paragraph.translation)
        translation_text.textChanged.connect(modify_translation)

        def save_translation():
            paragraph = self.table.current_paragraph()
            translation = translation_text.toPlainText()
            paragraph.translation = translation
            paragraph.engine_name = self.current_engine.name
            paragraph.target_lang = self.ebook.target_lang
            self.table.row.emit(paragraph.row)
            self.cache.update_paragraph(paragraph)
            self.status_worker.start[str, object].emit(
                _('Your changes have been saved.'),
                lambda: control.setVisible(False))
            translation_text.setFocus(Qt.OtherFocusReason)
        self.status_worker.show.connect(save_status.setText)
        save_button.clicked.connect(save_translation)

        return widget

    def layout_log(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        logging_text = QPlainTextEdit()
        logging_text.setPlaceholderText(_('Translation log'))
        logging_text.setReadOnly(True)
        layout.addWidget(logging_text)

        self.trans_worker.start.connect(logging_text.clear)
        self.trans_worker.logging.connect(logging_text.appendPlainText)

        return widget

    def get_progress_step(self, total):
        return int(round(100 / (total or 1), 2) * 100)

    def translate_all_paragraphs(self):
        message = _('Are you sure you want to translate all {:n} paragraphs?')
        paragraphs = self.table.get_seleted_items(True, True)
        self.prgress_step = self.get_progress_step(len(paragraphs))
        if len(paragraphs) < 1:
            paragraphs = self.table.get_seleted_items(False, True)
            self.prgress_step = self.get_progress_step(len(paragraphs))
            action = self.alert.ask(message.format(len(paragraphs)))
            if action == 'yes':
                self.translate_all = True
                self.trans_worker.translate.emit(paragraphs, True)
            return
        action = self.alert.ask(message.format(len(paragraphs)))
        if action == 'yes':
            self.translate_all = True
            self.trans_worker.translate.emit(paragraphs, False)

    def translate_selected_paragraph(self):
        paragraphs = self.table.get_seleted_items()
        if len(paragraphs) == self.table.rowCount():
            self.translate_all_paragraphs()
        else:
            self.prgress_step = self.get_progress_step(len(paragraphs))
            self.trans_worker.translate.emit(paragraphs, True)

    def install_widget_event(
            self, source, target, action, callback, stop=False):
        def eventFilter(self, object, event):
            event.type() == action and callback()
            return stop
        source.eventFilter = MethodType(eventFilter, source)
        target.installEventFilter(source)

    def terminate_translation(self):
        if self.on_working:
            action = self.alert.ask(
                _('Are you sure you want to stop the translation progress?'))
            if action != 'yes':
                return False
        self.trans_worker.set_cancelled(True)
        return True

    def done(self, result):
        if not self.terminate_translation():
            return
        self.preparation_thread.requestInterruption()
        self.preparation_thread.quit()
        self.preparation_thread.wait()
        self.trans_thread.quit()
        self.trans_thread.wait()
        self.status_thread.quit()
        self.status_thread.wait()
        if self.cache and not self.cache.is_persistence() and result == 0:
            self.cache.destroy()
        QDialog.done(self, result)
