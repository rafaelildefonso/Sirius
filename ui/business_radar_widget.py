import asyncio
import csv
import io
import json
import os
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSplitter, QTextEdit, QTextBrowser, QFrame, QDialog,
    QLineEdit, QSpinBox, QCheckBox, QMessageBox, QProgressBar,
    QSizePolicy, QApplication, QFileDialog
)
import qtawesome as qta


class C:
    BG        = "#050505"
    PANEL     = "#0c0c0c"
    PANEL2    = "#121212"
    BORDER    = "#1a1a1a"
    BORDER_B  = "#252525"
    PRI       = "#00aaff"
    PRI_DIM   = "#004466"
    PRI_GHO   = "rgba(0, 170, 255, 0.05)"
    ACC       = "#ff6b00"
    ACC2      = "#ffcc00"
    GREEN     = "#00ff88"
    GREEN_D   = "#00aa55"
    RED       = "#ff3355"
    TEXT      = "#e0f0ff"
    TEXT_DIM  = "#506070"
    TEXT_MED  = "#8090a0"
    WHITE     = "#ffffff"


class ScrapeWorker(QThread):
    finished = pyqtSignal(int)
    log_signal = pyqtSignal(str)

    def __init__(self, estado: str, max_results: int = 30):
        super().__init__()
        self.estado = estado
        self.max_results = max_results

    def run(self):
        total_new = 0
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            self.log_signal.emit("Iniciando busca no Google Maps...")
            from core.google_maps_scraper import scrape_maps_businesses
            new_biz = loop.run_until_complete(
                scrape_maps_businesses(self.estado, max_results=self.max_results)
            )
            total_new += new_biz
            self.log_signal.emit(f"Google Maps finalizado. {new_biz} novas empresas.")

            if total_new >= 0:
                self.log_signal.emit("Verificando sites das empresas...")
                from core.site_checker import check_all_sites
                checked = loop.run_until_complete(check_all_sites())
                self.log_signal.emit(f"Verificação de sites concluída. {checked} empresas verificadas.")

            if total_new >= 0:
                self.log_signal.emit("Iniciando análise de potencial via Gemini API...")
                from core.business_analyzer import analyze_all_businesses
                analyzed = analyze_all_businesses()
                self.log_signal.emit(f"Análise finalizada. {analyzed} empresas analisadas.")

            self.finished.emit(total_new)
        except Exception as e:
            self.log_signal.emit(f"Erro no processamento: {str(e)}")
            self.finished.emit(-1)


class BusinessProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar Perfil de Prospecção")
        self.setFixedSize(500, 400)
        self.setStyleSheet(f"""
            QDialog {{ background: {C.PANEL}; color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            QLabel {{ color: {C.TEXT_MED}; font-family: 'Inter'; font-size: 11px; }}
            QLineEdit, QSpinBox {{
                background: #080808; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 4px; padding: 6px;
                font-family: 'Inter';
            }}
            QLineEdit:focus, QSpinBox:focus {{ border: 1px solid {C.PRI}; }}
            QPushButton {{
                background: {C.PRI}; color: {C.BG};
                font-weight: bold; border-radius: 4px; border: none; height: 32px;
                font-family: 'Inter'; font-size: 11px;
            }}
            QPushButton:hover {{ background: {C.WHITE}; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        layout.addWidget(QLabel("ESTADO ALVO"))
        self.estado_in = QLineEdit()
        self.estado_in.setPlaceholderText("ex: SP, RJ, MG")
        layout.addWidget(self.estado_in)

        layout.addWidget(QLabel("SCORE MÍNIMO DE POTENCIAL"))
        self.score_in = QSpinBox()
        self.score_in.setRange(0, 100)
        self.score_in.setValue(60)
        self.score_in.setSuffix("%")
        layout.addWidget(self.score_in)

        layout.addWidget(QLabel("CATEGORIAS DE INTERESSE (separadas por vírgula)"))
        self.cat_in = QLineEdit()
        self.cat_in.setPlaceholderText("deixe vazio para todas")
        layout.addWidget(self.cat_in)

        layout.addWidget(QLabel("OBSERVAÇÕES"))
        self.obs_in = QLineEdit()
        self.obs_in.setPlaceholderText("ex: Foco em pequenas e médias empresas")
        layout.addWidget(self.obs_in)

        self.exclude_large_cb = QCheckBox("Excluir empresas de grande porte")
        self.exclude_large_cb.setStyleSheet(f"""
            QCheckBox {{ color: {C.TEXT}; font-family: 'Inter'; font-size: 11px; }}
            QCheckBox::indicator {{ width: 16px; height: 16px; }}
        """)
        layout.addWidget(self.exclude_large_cb)

        layout.addSpacing(10)

        save_btn = QPushButton("SALVAR CONFIGURAÇÕES")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

        self.load_profile()

    def load_profile(self):
        profile_path = Path(__file__).resolve().parent.parent / "config" / "user_profile_business.json"
        if profile_path.exists():
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                self.estado_in.setText(d.get("state", ""))
                self.score_in.setValue(d.get("min_potential_score", 60))
                self.cat_in.setText(", ".join(d.get("interest_categories", [])))
                self.obs_in.setText(d.get("notes", ""))
                self.exclude_large_cb.setChecked(d.get("exclude_large_companies", True))
            except Exception:
                pass

    def _save(self):
        profile_path = Path(__file__).resolve().parent.parent / "config" / "user_profile_business.json"
        data = {
            "state": self.estado_in.text().strip().upper(),
            "min_potential_score": self.score_in.value(),
            "interest_categories": [c.strip() for c in self.cat_in.text().split(",") if c.strip()],
            "notes": self.obs_in.text().strip(),
            "exclude_large_companies": self.exclude_large_cb.isChecked()
        }
        try:
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Não foi possível salvar: {e}")


class BusinessCard(QFrame):
    clicked = pyqtSignal(dict)

    def __init__(self, biz_data: dict, parent=None):
        super().__init__(parent)
        self.biz = biz_data
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedHeight(85)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        analysis = biz_data.get("analysis", {})
        self.score = analysis.get("purchase_potential", 0) if isinstance(analysis, dict) else 0

        if self.score >= 80:
            self.score_color = C.GREEN
        elif self.score >= 50:
            self.score_color = C.ACC2
        else:
            self.score_color = C.RED

        has_website = biz_data.get("has_website", False)
        self.site_color = C.GREEN if has_website else C.RED
        self.site_icon = "fa5s.check-circle" if has_website else "fa5s.times-circle"

        self.setStyleSheet(f"""
            BusinessCard {{
                background: {C.PANEL2};
                border: 1px solid {C.BORDER};
                border-radius: 6px;
            }}
            BusinessCard:hover {{
                border: 1px solid {C.PRI};
                background: {C.PANEL};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        score_lbl = QLabel(f"{self.score}%")
        score_lbl.setFixedSize(36, 36)
        score_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        score_lbl.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        score_lbl.setStyleSheet(f"""
            background: #000;
            color: {self.score_color};
            border: 2px solid {self.score_color};
            border-radius: 18px;
        """)
        layout.addWidget(score_lbl)

        size_label = QLabel()
        size = biz_data.get("analysis", {}).get("business_size", "") if isinstance(biz_data.get("analysis"), dict) else ""
        if size == "pequena":
            size_label.setPixmap(qta.icon("fa5s.building", color=C.GREEN).pixmap(12, 12))
            size_label.setToolTip("Pequena empresa")
        elif size == "media":
            size_label.setPixmap(qta.icon("fa5s.building", color=C.ACC2).pixmap(12, 12))
            size_label.setToolTip("Média empresa")
        elif size == "grande":
            size_label.setPixmap(qta.icon("fa5s.building", color=C.RED).pixmap(12, 12))
            size_label.setToolTip("Grande empresa")
        if size:
            layout.addWidget(size_label)

        info_lay = QVBoxLayout()
        info_lay.setSpacing(2)

        title_lbl = QLabel(biz_data.get("name", "Nome indisponível"))
        title_lbl.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {C.TEXT};")
        title_lbl.setWordWrap(True)
        info_lay.addWidget(title_lbl)

        category = biz_data.get("category", "")
        address = biz_data.get("address", "")
        info_text = category
        if address:
            info_text += f"  ·  {address}" if info_text else address
        info_lbl = QLabel(info_text if info_text else "Sem informações")
        info_lbl.setFont(QFont("Inter", 8))
        info_lbl.setStyleSheet(f"color: {C.TEXT_MED};")
        info_lbl.setWordWrap(True)
        info_lay.addWidget(info_lbl)

        layout.addLayout(info_lay, stretch=1)

        site_lbl = QLabel()
        site_lbl.setPixmap(qta.icon(self.site_icon, color=self.site_color).pixmap(14, 14))
        layout.addWidget(site_lbl)

        has_whatsapp = biz_data.get("site_check", {}).get("has_whatsapp", False)
        if has_whatsapp:
            wa_lbl = QLabel()
            wa_lbl.setPixmap(qta.icon("fa5b.whatsapp", color="#25D366").pixmap(14, 14))
            layout.addWidget(wa_lbl)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.biz)


class BusinessRadarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {C.BG};")
        self._businesses = []
        self._selected_biz = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        hdr = QHBoxLayout()

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.search-location", color=C.PRI).pixmap(20, 20))
        hdr.addWidget(icon_lbl)

        title_lbl = QLabel("RADAR DE PROSPECÇÃO")
        title_lbl.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {C.TEXT};")
        hdr.addWidget(title_lbl)

        hdr.addStretch()

        self.profile_btn = QPushButton(" MEU PERFIL")
        self.profile_btn.setIcon(qta.icon("fa5s.user-cog", color=C.TEXT))
        self.profile_btn.setFixedSize(110, 28)
        self.profile_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.profile_btn.setStyleSheet(f"""
            QPushButton {{ background: {C.PANEL}; color: {C.TEXT}; border: 1px solid {C.BORDER}; border-radius: 4px; font-family: 'Inter'; font-size: 9px; font-weight: bold; }}
            QPushButton:hover {{ border: 1px solid {C.PRI}; color: {C.PRI}; }}
        """)
        self.profile_btn.clicked.connect(self._open_profile)
        hdr.addWidget(self.profile_btn)

        self.refresh_btn = QPushButton(" PROSPECTAR")
        self.refresh_btn.setIcon(qta.icon("fa5s.search", color=C.TEXT))
        self.refresh_btn.setFixedSize(130, 28)
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setStyleSheet(f"""
            QPushButton {{ background: {C.PRI}; color: {C.BG}; border: none; border-radius: 4px; font-family: 'Inter'; font-size: 9px; font-weight: bold; }}
            QPushButton:hover {{ background: {C.WHITE}; }}
        """)
        self.refresh_btn.clicked.connect(self._start_scanning)
        hdr.addWidget(self.refresh_btn)

        self.clear_btn = QPushButton(" LIMPAR")
        self.clear_btn.setIcon(qta.icon("fa5s.trash-alt", color=C.RED))
        self.clear_btn.setFixedSize(95, 28)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.RED}; border: 1px solid {C.RED}; border-radius: 4px; font-family: 'Inter'; font-size: 9px; font-weight: bold; }}
            QPushButton:hover {{ background: rgba(255, 51, 85, 0.15); }}
        """)
        self.clear_btn.clicked.connect(self._clear_businesses)
        hdr.addWidget(self.clear_btn)

        layout.addLayout(hdr)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_row.addWidget(QLabel("ESTADO:"))
        self.estado_input = QLineEdit()
        self.estado_input.setPlaceholderText("SP")
        self.estado_input.setFixedWidth(50)
        self.estado_input.setStyleSheet(f"""
            QLineEdit {{ background: #080808; color: {C.WHITE}; border: 1px solid {C.BORDER};
                        border-radius: 3px; padding: 2px 6px; font-family: 'Inter'; font-size: 9px; }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        filter_row.addWidget(self.estado_input)

        filter_row.addSpacing(8)

        filter_row.addWidget(QLabel("LIMITE:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 100)
        self.limit_spin.setValue(30)
        self.limit_spin.setFixedWidth(55)
        self.limit_spin.setStyleSheet(f"""
            QSpinBox {{ background: #080808; color: {C.WHITE}; border: 1px solid {C.BORDER};
                        border-radius: 3px; padding: 2px 4px; font-family: 'Inter'; font-size: 9px; }}
            QSpinBox:focus {{ border: 1px solid {C.PRI}; }}
        """)
        filter_row.addWidget(self.limit_spin)

        filter_row.addSpacing(8)

        filter_row.addWidget(QLabel("POT. MÍN:"))
        self.min_score_spin = QSpinBox()
        self.min_score_spin.setRange(0, 100)
        self.min_score_spin.setValue(0)
        self.min_score_spin.setSuffix("%")
        self.min_score_spin.setFixedWidth(60)
        self.min_score_spin.setStyleSheet(f"""
            QSpinBox {{ background: #080808; color: {C.WHITE}; border: 1px solid {C.BORDER};
                        border-radius: 3px; padding: 2px 4px; font-family: 'Inter'; font-size: 9px; }}
            QSpinBox:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self.min_score_spin.valueChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.min_score_spin)

        filter_row.addStretch()

        self.filter_count_lbl = QLabel("")
        self.filter_count_lbl.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        self.filter_count_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        filter_row.addWidget(self.filter_count_lbl)

        layout.addLayout(filter_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{ background: transparent; border: none; }}
            QProgressBar::chunk {{ background: {C.PRI}; }}
        """)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.log_lbl = QLabel("")
        self.log_lbl.setFont(QFont("Inter", 8))
        self.log_lbl.setStyleSheet(f"color: {C.PRI};")
        self.log_lbl.hide()
        layout.addWidget(self.log_lbl)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{ background: {C.BORDER}; width: 1px; }}
        """)

        left_widget = QWidget()
        left_widget.setMinimumWidth(280)
        left_lay = QVBoxLayout(left_widget)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(6)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { background: transparent; width: 4px; }
            QScrollBar::handle:vertical { background: #1a1a1a; border-radius: 2px; }
        """)

        self.scroll_content = QWidget()
        self.scroll_lay = QVBoxLayout(self.scroll_content)
        self.scroll_lay.setContentsMargins(0, 0, 4, 0)
        self.scroll_lay.setSpacing(6)
        self.scroll_lay.addStretch()

        self.scroll.setWidget(self.scroll_content)
        left_lay.addWidget(self.scroll)
        splitter.addWidget(left_widget)

        self.details_widget = QWidget()
        self.details_widget.setStyleSheet(f"background: {C.PANEL}; border-radius: 8px; border: 1px solid {C.BORDER};")
        self.details_lay = QVBoxLayout(self.details_widget)
        self.details_lay.setContentsMargins(16, 16, 16, 16)
        self.details_lay.setSpacing(12)

        self._build_empty_details()
        splitter.addWidget(self.details_widget)

        splitter.setSizes([340, 500])
        layout.addWidget(splitter, stretch=1)

        self.load_businesses()

    def _build_empty_details(self):
        while self.details_lay.count():
            item = self.details_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        lbl = QLabel("Selecione uma empresa para ver a análise de potencial.")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFont(QFont("Inter", 9))
        lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
        self.details_lay.addWidget(lbl)

    def load_businesses(self):
        for i in reversed(range(self.scroll_lay.count())):
            item = self.scroll_lay.itemAt(i)
            if item.widget():
                item.widget().deleteLater()

        biz_path = Path(__file__).resolve().parent.parent / "memory" / "business_prospects.json"
        if biz_path.exists():
            try:
                with open(biz_path, "r", encoding="utf-8") as f:
                    self._businesses = json.load(f)
            except Exception:
                self._businesses = []

        profile_path = Path(__file__).resolve().parent.parent / "config" / "user_profile_business.json"
        exclude_large = True
        if profile_path.exists():
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    profile = json.load(f)
                    exclude_large = profile.get("exclude_large_companies", True)
            except Exception:
                pass

        min_score = self.min_score_spin.value() if hasattr(self, "min_score_spin") else 0

        if not self._businesses:
            lbl = QLabel("Nenhuma empresa encontrada.\nClique em 'Prospectar' para iniciar a busca no Google Maps.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFont(QFont("Inter", 9))
            lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
            self.scroll_lay.addWidget(lbl)
            self.filter_count_lbl.setText("0 empresas")
        else:
            def sort_key(b):
                try:
                    score = b.get("analysis", {}).get("purchase_potential", 0)
                except Exception:
                    score = 0
                has_whatsapp = b.get("site_check", {}).get("has_whatsapp", False)
                size = b.get("analysis", {}).get("business_size", "") if isinstance(b.get("analysis"), dict) else ""
                size_priority = 0 if size == "grande" else (1 if size == "media" else 2)
                return (has_whatsapp, size_priority, score)
            self._businesses.sort(key=sort_key, reverse=True)

            visible_count = 0
            excluded_large = 0
            for biz in self._businesses:
                score = biz.get("analysis", {}).get("purchase_potential", 0) or 0
                if score < min_score:
                    continue
                biz_size = biz.get("analysis", {}).get("business_size", "") if isinstance(biz.get("analysis"), dict) else ""
                if exclude_large and biz_size == "grande":
                    excluded_large += 1
                    continue
                card = BusinessCard(biz)
                card.clicked.connect(self.show_details)
                self.scroll_lay.addWidget(card)
                visible_count += 1

            total = len(self._businesses)
            excluded_text = f" ({excluded_large} grandes excluídas)" if excluded_large else ""
            self.filter_count_lbl.setText(f"{visible_count} de {total} empresas{excluded_text}")
            if visible_count == 0 and total > 0:
                lbl = QLabel(
                    f"Nenhuma empresa com potencial ≥ {min_score}%.\n"
                    "Reduza o filtro de POT. MÍN para ver mais resultados."
                )
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setFont(QFont("Inter", 9))
                lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
                self.scroll_lay.addWidget(lbl)

        self.scroll_lay.addStretch()

    def show_details(self, biz: dict):
        self._selected_biz = biz
        while self.details_lay.count():
            item = self.details_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        analysis = biz.get("analysis", {})

        header = QHBoxLayout()
        header_text = QVBoxLayout()
        header_text.setSpacing(2)

        name = QLabel(biz.get("name"))
        name.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        name.setStyleSheet(f"color: {C.WHITE};")
        header_text.addWidget(name)

        info_parts = []
        if biz.get("category"):
            info_parts.append(biz.get("category"))
        if biz.get("address"):
            info_parts.append(biz.get("address"))
        info_line = QLabel("  ·  ".join(info_parts) if info_parts else "Sem informações")
        info_line.setFont(QFont("Inter", 9))
        info_line.setStyleSheet(f"color: {C.PRI};")
        header_text.addWidget(info_line)
        header.addLayout(header_text)

        header.addStretch()

        if biz.get("website"):
            site_btn = QPushButton(" ABRIR SITE")
            site_btn.setIcon(qta.icon("fa5s.external-link-alt", color=C.TEXT))
            site_btn.setFixedSize(110, 32)
            site_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            site_btn.setStyleSheet(f"""
                QPushButton {{ background: {C.PRI}; color: {C.BG}; border: none; border-radius: 4px; font-family: 'Inter'; font-size: 9px; font-weight: bold; }}
                QPushButton:hover {{ background: {C.WHITE}; }}
            """)
            site_btn.clicked.connect(self._open_website)
            header.addWidget(site_btn)

        self.details_lay.addLayout(header)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {C.BORDER};")
        self.details_lay.addWidget(line)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        if analysis:
            score = analysis.get("purchase_potential", 0)
            score_col = C.GREEN if score >= 80 else (C.ACC2 if score >= 50 else C.RED)

            score_row = QHBoxLayout()
            score_lbl = QLabel(f"Potencial de Compra: {score}%")
            score_lbl.setFont(QFont("Inter", 10, QFont.Weight.Bold))
            score_lbl.setStyleSheet(f"color: {score_col};")
            score_row.addWidget(score_lbl)
            score_row.addStretch()
            lay.addLayout(score_row)

            self._add_section(lay, "Motivo", analysis.get("reason", ""), "fa5s.info-circle", C.PRI)
            self._add_section(lay, "Abordagem Recomendada", analysis.get("recommended_approach", ""), "fa5s.lightbulb", C.ACC)

            red_flags = analysis.get("red_flags", [])
            if red_flags:
                self._add_red_flags_section(lay, red_flags)

            self._add_section(lay, "Categoria", analysis.get("category", biz.get("category", "Não classificada")), "fa5s.tag", C.GREEN)
        else:
            lbl = QLabel("Esta empresa ainda não foi analisada. Aguarde a triagem inteligente.")
            lbl.setFont(QFont("Inter", 9))
            lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
            lay.addWidget(lbl)

        contact_grp = QVBoxLayout()
        contact_grp.setSpacing(4)
        t_lbl = QLabel(" CONTATO")
        t_lbl.setFont(QFont("Inter", 7, QFont.Weight.Bold))
        t_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        contact_grp.addWidget(t_lbl)

        contact_info = []
        if biz.get("phone"):
            contact_info.append(f"📞 {biz.get('phone')}")
        if biz.get("website"):
            contact_info.append(f"🌐 {biz.get('website')}")
        if biz.get("rating"):
            contact_info.append(f"⭐ {biz.get('rating')}")
        if biz.get("reviews"):
            contact_info.append(f"📝 {biz.get('reviews')}")

        for info in contact_info:
            lbl = QLabel(info)
            lbl.setFont(QFont("Inter", 9))
            lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
            contact_grp.addWidget(lbl)

        lay.addLayout(contact_grp)

        if biz.get("site_check"):
            site = biz.get("site_check", {})
            site_grp = QVBoxLayout()
            site_grp.setSpacing(4)
            s_lbl = QLabel(" ANÁLISE DO SITE")
            s_lbl.setFont(QFont("Inter", 7, QFont.Weight.Bold))
            s_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            site_grp.addWidget(s_lbl)

            quality = site.get("quality", "unknown")
            q_color = C.GREEN if quality == "bom" else (C.ACC2 if quality == "medio" else C.RED)
            q_lbl = QLabel(f"Qualidade: {quality}")
            q_lbl.setFont(QFont("Inter", 9))
            q_lbl.setStyleSheet(f"color: {q_color}; background: transparent;")
            site_grp.addWidget(q_lbl)

            if site.get("load_time_ms"):
                site_grp.addWidget(QLabel(f"Carregamento: {site.get('load_time_ms')}ms"))
            if site.get("has_viewport"):
                site_grp.addWidget(QLabel("✓ Responsivo"))
            else:
                site_grp.addWidget(QLabel("✗ Não responsivo"))
            if site.get("has_analytics"):
                site_grp.addWidget(QLabel("✓ Google Analytics"))
            if site.get("has_whatsapp"):
                site_grp.addWidget(QLabel("✓ WhatsApp"))

            lay.addLayout(site_grp)

        scroll.setWidget(content)
        self.details_lay.addWidget(scroll)

        export_row = QHBoxLayout()
        export_row.addStretch()

        csv_btn = QPushButton(" EXPORTAR CSV")
        csv_btn.setIcon(qta.icon("fa5s.file-csv", color=C.GREEN))
        csv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        csv_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.GREEN}; border: 1px solid {C.GREEN}; border-radius: 4px; padding: 6px 14px; font-family: 'Inter'; font-size: 9px; font-weight: bold; }}
            QPushButton:hover {{ background: rgba(0, 255, 136, 0.1); }}
        """)
        csv_btn.clicked.connect(self._export_csv)
        export_row.addWidget(csv_btn)

        json_btn = QPushButton(" EXPORTAR JSON")
        json_btn.setIcon(qta.icon("fa5s.file-code", color=C.ACC))
        json_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        json_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.ACC}; border: 1px solid {C.ACC}; border-radius: 4px; padding: 6px 14px; font-family: 'Inter'; font-size: 9px; font-weight: bold; }}
            QPushButton:hover {{ background: rgba(255, 107, 0, 0.1); }}
        """)
        json_btn.clicked.connect(self._export_json)
        export_row.addWidget(json_btn)

        self.details_lay.addLayout(export_row)

    def _add_section(self, parent_layout, title: str, content: str, icon: str, color: str):
        sec = QVBoxLayout()
        sec.setSpacing(4)
        t_lbl = QLabel(f" {title.upper()}")
        t_lbl.setFont(QFont("Inter", 7, QFont.Weight.Bold))
        t_lbl.setStyleSheet(f"color: {color}; background: transparent;")
        sec.addWidget(t_lbl)

        txt = QTextBrowser()
        txt.setFont(QFont("Inter", 9))
        txt.setStyleSheet(f"color: {C.TEXT}; background: transparent; border: none;")
        txt.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        txt.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        txt.setPlainText(content)
        sec.addWidget(txt)

        parent_layout.addLayout(sec)

    def _add_red_flags_section(self, parent_layout, red_flags: list):
        sec = QVBoxLayout()
        sec.setSpacing(4)

        t_lbl = QLabel(" PONTOS DE ALERTA")
        t_lbl.setFont(QFont("Inter", 7, QFont.Weight.Bold))
        t_lbl.setStyleSheet(f"color: {C.RED}; background: transparent;")
        sec.addWidget(t_lbl)

        for flag in red_flags:
            row = QHBoxLayout()
            ico = QLabel()
            ico.setPixmap(qta.icon("fa5s.flag", color=C.RED).pixmap(10, 10))
            row.addWidget(ico)

            lbl = QTextBrowser()
            lbl.setFont(QFont("Inter", 9))
            lbl.setStyleSheet(f"color: {C.WHITE}; background: transparent; border: none;")
            lbl.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            lbl.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            lbl.setPlainText(flag)
            row.addWidget(lbl, stretch=1)
            sec.addLayout(row)

        parent_layout.addLayout(sec)

    def _open_profile(self):
        dialog = BusinessProfileDialog(self)
        dialog.exec()
        estado = self.estado_input.text().strip().upper() or "SP"
        profile_path = Path(__file__).resolve().parent.parent / "config" / "user_profile_business.json"
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self.estado_input.setText(d.get("state", estado))
        except Exception:
            pass

    def _open_website(self):
        if self._selected_biz and self._selected_biz.get("website"):
            import webbrowser
            webbrowser.open(self._selected_biz.get("website"))

    def _on_filter_changed(self):
        self.load_businesses()

    def _start_scanning(self):
        estado = self.estado_input.text().strip().upper() or "SP"
        max_results = self.limit_spin.value() if hasattr(self, "limit_spin") else 30

        self.progress_bar.show()
        self.log_lbl.setText(f"Iniciando Radar de Prospecção para '{estado}'...")
        self.log_lbl.show()
        self.refresh_btn.setEnabled(False)

        self.worker = ScrapeWorker(estado, max_results=max_results)
        self.worker.log_signal.connect(self._update_log)
        self.worker.finished.connect(self._scan_finished)
        self.worker.start()

    def _update_log(self, text: str):
        self.log_lbl.setText(text)

    def _scan_finished(self, total_new):
        self.progress_bar.hide()
        self.refresh_btn.setEnabled(True)
        if total_new >= 0:
            self.log_lbl.setText(
                f"Prospecção finalizada! {total_new} novas empresas encontradas."
            )
            self.load_businesses()
        else:
            self.log_lbl.setText("Erro ao executar prospecção. Verifique os logs do console.")

    def _clear_businesses(self):
        reply = QMessageBox.question(
            self, "Limpar Dados",
            "Tem certeza que deseja limpar todas as empresas do radar de prospecção?\n\nEsta ação não pode ser desfeita.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        biz_path = Path(__file__).resolve().parent.parent / "memory" / "business_prospects.json"
        try:
            with open(biz_path, "w", encoding="utf-8") as f:
                json.dump([], f)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Não foi possível limpar os dados: {e}")
            return

        self._businesses = []
        self._selected_biz = None
        self.load_businesses()
        self.log_lbl.setText("Dados de prospecção limpos.")
        self.log_lbl.show()

    def _export_csv(self):
        if not self._businesses:
            QMessageBox.information(self, "Exportar", "Nenhuma empresa para exportar.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar CSV", "prospeccao_empresas.csv", "CSV (*.csv)"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Nome", "Categoria", "Endereço", "Telefone", "Website",
                    "Rating", "Avaliações", "Tem Site", "Qualidade Site",
                    "Potencial", "Motivo", "Abordagem", "Red Flags"
                ])
                for biz in self._businesses:
                    analysis = biz.get("analysis", {})
                    site_check = biz.get("site_check", {})
                    writer.writerow([
                        biz.get("name", ""),
                        analysis.get("category", biz.get("category", "")),
                        biz.get("address", ""),
                        biz.get("phone", ""),
                        biz.get("website", ""),
                        biz.get("rating", ""),
                        biz.get("reviews", ""),
                        "Sim" if biz.get("has_website") else "Não",
                        site_check.get("quality", ""),
                        analysis.get("purchase_potential", ""),
                        analysis.get("reason", ""),
                        analysis.get("recommended_approach", ""),
                        "; ".join(analysis.get("red_flags", []))
                    ])
            self.log_lbl.setText(f"CSV exportado: {path}")
            self.log_lbl.show()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao exportar CSV: {e}")

    def _export_json(self):
        if not self._businesses:
            QMessageBox.information(self, "Exportar", "Nenhuma empresa para exportar.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar JSON", "prospeccao_empresas.json", "JSON (*.json)"
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._businesses, f, indent=4, ensure_ascii=False)
            self.log_lbl.setText(f"JSON exportado: {path}")
            self.log_lbl.show()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao exportar JSON: {e}")
