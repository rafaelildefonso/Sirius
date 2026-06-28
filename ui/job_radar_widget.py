# ui/job_radar_widget.py
import asyncio
import json
import os
from pathlib import Path
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QColor, QBrush, QPainter, QPen
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSplitter, QTextEdit, QTextBrowser, QFrame, QDialog,
    QLineEdit, QPlainTextEdit, QSpinBox, QMessageBox, QProgressBar,
    QSizePolicy
)
import qtawesome as qta

# Import constants/helpers from ui if possible, or define them here for autonomy
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

def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c

class ScrapeWorker(QThread):
    finished = pyqtSignal(int)
    log_signal = pyqtSignal(str)

    def __init__(self, keywords: str, max_jobs: int = 10, sources: list | None = None):
        super().__init__()
        self.keywords = keywords
        self.max_jobs = max_jobs
        self.sources = sources or ["linkedin", "google_jobs"]

    def run(self):
        total_new = 0
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            if "linkedin" in self.sources:
                self.log_signal.emit("Iniciando scraper do LinkedIn...")
                from core.linkedin_scraper import scrape_linkedin_jobs
                new_jobs = loop.run_until_complete(
                    scrape_linkedin_jobs(self.keywords, max_jobs=self.max_jobs)
                )
                total_new += new_jobs
                self.log_signal.emit(f"LinkedIn finalizado. {new_jobs} novas vagas.")

            if "google_jobs" in self.sources:
                self.log_signal.emit("Procurando vagas no Google Jobs...")
                from core.google_jobs_scraper import scrape_google_jobs
                new_jobs = loop.run_until_complete(
                    scrape_google_jobs(self.keywords, max_jobs=self.max_jobs)
                )
                total_new += new_jobs
                self.log_signal.emit(f"Google Jobs finalizado. {new_jobs} novas vagas.")

            if total_new >= 0:
                self.log_signal.emit("Iniciando análise de compatibilidade via Gemini API...")
                from core.job_analyzer import analyze_all_jobs
                analyzed = analyze_all_jobs()
                self.log_signal.emit(f"Análise finalizada. {analyzed} vagas analisadas.")

            self.finished.emit(total_new)
        except Exception as e:
            self.log_signal.emit(f"Erro no processamento: {str(e)}")
            self.finished.emit(-1)

# Edit Profile Dialog
class ProfileDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar Perfil de Candidato")
        self.setFixedSize(500, 600)
        self.setStyleSheet(f"""
            QDialog {{ background: {C.PANEL}; color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            QLabel {{ color: {C.TEXT_MED}; font-family: 'Inter'; font-size: 11px; }}
            QLineEdit, QPlainTextEdit, QSpinBox {{
                background: #080808; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 4px; padding: 6px;
                font-family: 'Inter';
            }}
            QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{ border: 1px solid {C.PRI}; }}
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
        
        # Fields
        layout.addWidget(QLabel("NOME COMPLETO"))
        self.name_in = QLineEdit()
        layout.addWidget(self.name_in)
        
        layout.addWidget(QLabel("CARGO ATUAL / PRETENDIDO"))
        self.title_in = QLineEdit()
        layout.addWidget(self.title_in)
        
        layout.addWidget(QLabel("RESUMO PROFISSIONAL / MINI BIO"))
        self.bio_in = QPlainTextEdit()
        self.bio_in.setFixedHeight(80)
        layout.addWidget(self.bio_in)
        
        layout.addWidget(QLabel("SKILLS / TECNOLOGIAS (Separadas por vírgula)"))
        self.skills_in = QLineEdit()
        layout.addWidget(self.skills_in)
        
        row = QHBoxLayout()
        v_exp = QVBoxLayout()
        v_exp.addWidget(QLabel("ANOS DE EXP."))
        self.exp_in = QSpinBox()
        self.exp_in.setRange(0, 30)
        v_exp.addWidget(self.exp_in)
        row.addLayout(v_exp)
        
        v_sal = QVBoxLayout()
        v_sal.addWidget(QLabel("PRETENSÃO SALARIAL"))
        self.sal_in = QLineEdit()
        v_sal.addWidget(self.sal_in)
        row.addLayout(v_sal)
        layout.addLayout(row)
        
        layout.addWidget(QLabel("CARGOS ALVO (Separados por vírgula)"))
        self.roles_in = QLineEdit()
        layout.addWidget(self.roles_in)
        
        layout.addWidget(QLabel("PALAVRAS-CHAVE A EVITAR (Separadas por vírgula)"))
        self.avoid_in = QLineEdit()
        layout.addWidget(self.avoid_in)
        
        layout.addSpacing(10)
        
        save_btn = QPushButton("SALVAR CONFIGURAÇÕES")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)
        
        self.load_profile()
        
    def load_profile(self):
        profile_path = Path(__file__).resolve().parent.parent / "config" / "user_profile.json"
        if profile_path.exists():
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                self.name_in.setText(d.get("full_name", ""))
                self.title_in.setText(d.get("title", ""))
                self.bio_in.setPlainText(d.get("resume_summary", ""))
                self.skills_in.setText(", ".join(d.get("skills", [])))
                self.exp_in.setValue(d.get("experience_years", 0))
                self.sal_in.setText(d.get("salary_expectation", ""))
                self.roles_in.setText(", ".join(d.get("target_roles", [])))
                self.avoid_in.setText(", ".join(d.get("avoid_keywords", [])))
            except:
                pass
                
    def _save(self):
        profile_path = Path(__file__).resolve().parent.parent / "config" / "user_profile.json"
        data = {
            "full_name": self.name_in.text().strip(),
            "title": self.title_in.text().strip(),
            "resume_summary": self.bio_in.toPlainText().strip(),
            "skills": [s.strip() for s in self.skills_in.text().split(",") if s.strip()],
            "experience_years": self.exp_in.value(),
            "preferred_location": "Remoto",  # Defaulting
            "salary_expectation": self.sal_in.text().strip(),
            "target_roles": [r.strip() for r in self.roles_in.text().split(",") if r.strip()],
            "avoid_keywords": [a.strip() for a in self.avoid_in.text().split(",") if a.strip()]
        }
        try:
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Não foi possível salvar: {e}")

class JobCard(QFrame):
    clicked = pyqtSignal(dict)
    
    def __init__(self, job_data: dict, parent=None):
        super().__init__(parent)
        self.job = job_data
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedHeight(85)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.analysis = job_data.get("analysis", {})
        self.score = self.analysis.get("match_score", 0) if isinstance(self.analysis, dict) else 0
        
        # Color based on score
        if self.score >= 80:
            self.score_color = C.GREEN
        elif self.score >= 50:
            self.score_color = C.ACC2
        else:
            self.score_color = C.RED
            
        self.setStyleSheet(f"""
            JobCard {{
                background: {C.PANEL2};
                border: 1px solid {C.BORDER};
                border-radius: 6px;
            }}
            JobCard:hover {{
                border: 1px solid {C.PRI};
                background: {C.PANEL};
            }}
        """)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        
        # Match Score Circle
        self.score_lbl = QLabel(f"{self.score}%")
        self.score_lbl.setFixedSize(36, 36)
        self.score_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.score_lbl.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        self.score_lbl.setStyleSheet(f"""
            background: #000;
            color: {self.score_color};
            border: 2px solid {self.score_color};
            border-radius: 18px;
        """)
        layout.addWidget(self.score_lbl)
        
        # Info
        info_lay = QVBoxLayout()
        info_lay.setSpacing(2)
        
        self.title_lbl = QLabel(job_data.get("title", "Título indisponível"))
        self.title_lbl.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet(f"color: {C.TEXT};")
        self.title_lbl.setWordWrap(True)
        info_lay.addWidget(self.title_lbl)
        
        self.company_lbl = QLabel(f"{job_data.get('company')}  ·  {job_data.get('location')}")
        self.company_lbl.setFont(QFont("Inter", 8))
        self.company_lbl.setStyleSheet(f"color: {C.TEXT_MED};")
        info_lay.addWidget(self.company_lbl)
        
        layout.addLayout(info_lay, stretch=1)
        
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.job)

class JobRadarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {C.BG};")
        self._jobs = []
        self._selected_job = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        
        # ── Header ──────────────────────────────────────────
        hdr = QHBoxLayout()
        
        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon("fa5s.broadcast-tower", color=C.PRI).pixmap(20, 20))
        hdr.addWidget(icon_lbl)
        
        title_lbl = QLabel("RADAR INTELIGENTE DE VAGAS")
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
        
        self.refresh_btn = QPushButton(" BUSCAR VAGAS")
        self.refresh_btn.setIcon(qta.icon("fa5s.search", color=C.TEXT))
        self.refresh_btn.setFixedSize(130, 28)
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setStyleSheet(f"""
            QPushButton {{ background: {C.PRI}; color: {C.BG}; border: none; border-radius: 4px; font-family: 'Inter'; font-size: 9px; font-weight: bold; }}
            QPushButton:hover {{ background: {C.WHITE}; }}
        """)
        self.refresh_btn.clicked.connect(self._start_scanning)
        hdr.addWidget(self.refresh_btn)
        
        layout.addLayout(hdr)
        
        # ── Filter Row ──────────────────────────────────────
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_row.addWidget(QLabel("LIMITE:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 50)
        self.limit_spin.setValue(8)
        self.limit_spin.setFixedWidth(55)
        self.limit_spin.setStyleSheet(f"""
            QSpinBox {{ background: #080808; color: {C.WHITE}; border: 1px solid {C.BORDER};
                        border-radius: 3px; padding: 2px 4px; font-family: 'Inter'; font-size: 9px; }}
            QSpinBox:focus {{ border: 1px solid {C.PRI}; }}
        """)
        filter_row.addWidget(self.limit_spin)

        filter_row.addSpacing(8)

        filter_row.addWidget(QLabel("MATCH MÍN:"))
        self.min_match_spin = QSpinBox()
        self.min_match_spin.setRange(0, 100)
        self.min_match_spin.setValue(0)
        self.min_match_spin.setSuffix("%")
        self.min_match_spin.setFixedWidth(60)
        self.min_match_spin.setStyleSheet(f"""
            QSpinBox {{ background: #080808; color: {C.WHITE}; border: 1px solid {C.BORDER};
                        border-radius: 3px; padding: 2px 4px; font-family: 'Inter'; font-size: 9px; }}
            QSpinBox:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self.min_match_spin.valueChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.min_match_spin)

        filter_row.addSpacing(12)

        self.source_lbl = QLabel("\uf085  LinkedIn  ·  Google Jobs")
        self.source_lbl.setFont(QFont("Inter", 7))
        self.source_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        filter_row.addWidget(self.source_lbl)

        filter_row.addStretch()

        self.filter_count_lbl = QLabel("")
        self.filter_count_lbl.setFont(QFont("Inter", 8, QFont.Weight.Bold))
        self.filter_count_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        filter_row.addWidget(self.filter_count_lbl)

        layout.addLayout(filter_row)

        # Progress Bar
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
        
        # Loader log
        self.log_lbl = QLabel("")
        self.log_lbl.setFont(QFont("Inter", 8))
        self.log_lbl.setStyleSheet(f"color: {C.PRI};")
        self.log_lbl.hide()
        layout.addWidget(self.log_lbl)
        
        # ── Body Splitter ───────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{ background: {C.BORDER}; width: 1px; }}
        """)
        
        # Left Panel (List)
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
        
        # Right Panel (Details)
        self.details_widget = QWidget()
        self.details_widget.setStyleSheet(f"background: {C.PANEL}; border-radius: 8px; border: 1px solid {C.BORDER};")
        self.details_lay = QVBoxLayout(self.details_widget)
        self.details_lay.setContentsMargins(16, 16, 16, 16)
        self.details_lay.setSpacing(12)
        
        self._build_empty_details()
        splitter.addWidget(self.details_widget)
        
        splitter.setSizes([340, 500])
        layout.addWidget(splitter, stretch=1)
        
        self.load_jobs()
        
    def _build_empty_details(self):
        # Clear layout
        while self.details_lay.count():
            item = self.details_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        lbl = QLabel("Selecione uma vaga para ver os detalhes da triagem inteligente.")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFont(QFont("Inter", 9))
        lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
        self.details_lay.addWidget(lbl)
        
    def load_jobs(self):
        # Clear current cards
        for i in reversed(range(self.scroll_lay.count())):
            item = self.scroll_lay.itemAt(i)
            if item.widget():
                item.widget().deleteLater()
                
        jobs_path = Path(__file__).resolve().parent.parent / "memory" / "linkedin_jobs.json"
        if jobs_path.exists():
            try:
                with open(jobs_path, "r", encoding="utf-8") as f:
                    self._jobs = json.load(f)
            except:
                self._jobs = []
                
        min_score = self.min_match_spin.value() if hasattr(self, 'min_match_spin') else 0
        
        if not self._jobs:
            lbl = QLabel("Nenhuma vaga encontrada no radar.\nClique em 'Buscar Vagas' para monitorar.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFont(QFont("Inter", 9))
            lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
            self.scroll_lay.addWidget(lbl)
            self.filter_count_lbl.setText("0 vagas")
        else:
            # Sort by match score if exists
            def get_score(j):
                try: return j.get("analysis", {}).get("match_score", 0)
                except: return 0
            self._jobs.sort(key=get_score, reverse=True)
            
            visible_count = 0
            for job in self._jobs:
                score = get_score(job)
                if score < min_score:
                    continue
                card = JobCard(job)
                card.clicked.connect(self.show_details)
                self.scroll_lay.addWidget(card)
                visible_count += 1
                
            total = len(self._jobs)
            self.filter_count_lbl.setText(f"{visible_count} de {total} vagas")
            if visible_count == 0 and total > 0:
                lbl = QLabel(f"Nenhuma vaga com match ≥ {min_score}%.\nReduza o filtro de MATCH MÍN para ver mais resultados.")
                lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lbl.setFont(QFont("Inter", 9))
                lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
                self.scroll_lay.addWidget(lbl)
                
        self.scroll_lay.addStretch()
        
    def show_details(self, job: dict):
        self._selected_job = job
        # Clear layout
        while self.details_lay.count():
            item = self.details_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        analysis = job.get("analysis", {})
        
        # Header Info
        header = QHBoxLayout()
        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        
        title = QLabel(job.get("title"))
        title.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.WHITE};")
        header_text.addWidget(title)
        
        company = QLabel(f"{job.get('company')}  ·  {job.get('location')}")
        company.setFont(QFont("Inter", 9))
        company.setStyleSheet(f"color: {C.PRI};")
        header_text.addWidget(company)
        header.addLayout(header_text)
        
        # Apply Button
        apply_btn = QPushButton(" CANDIDATAR-SE")
        apply_btn.setIcon(qta.icon("fa5s.external-link-alt", color=C.TEXT))
        apply_btn.setFixedSize(140, 32)
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(f"""
            QPushButton {{ background: {C.GREEN}; color: {C.BG}; border: none; border-radius: 4px; font-family: 'Inter'; font-size: 9px; font-weight: bold; }}
            QPushButton:hover {{ background: {C.WHITE}; }}
        """)
        apply_btn.clicked.connect(self._open_job_url)
        header.addWidget(apply_btn)
        self.details_lay.addLayout(header)
        
        # Separator line
        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {C.BORDER};")
        self.details_lay.addWidget(line)
        
        # Scroll area for details
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        
        if analysis:
            score = analysis.get("match_score", 0)
            score_col = C.GREEN if score >= 80 else (C.ACC2 if score >= 50 else C.RED)
            
            # Score card
            score_row = QHBoxLayout()
            score_lbl = QLabel(f"Match Score: {score}%")
            score_lbl.setFont(QFont("Inter", 10, QFont.Weight.Bold))
            score_lbl.setStyleSheet(f"color: {score_col};")
            score_row.addWidget(score_lbl)
            score_row.addStretch()
            lay.addLayout(score_row)
            
            # Summary
            self._add_section(lay, "Resumo da Oportunidade", analysis.get("summary", ""), "fa5s.info-circle", C.PRI)
            
            # Pros & Gaps Columns
            cols = QHBoxLayout()
            pros_widget = QWidget()
            pros_lay = QVBoxLayout(pros_widget); pros_lay.setContentsMargins(0,0,0,0)
            self._add_bullet_section(pros_lay, "Pontos Positivos (Fit)", analysis.get("fit_reason", ""), "fa5s.plus", C.GREEN)
            cols.addWidget(pros_widget)
            
            gaps_widget = QWidget()
            gaps_lay = QVBoxLayout(gaps_widget); gaps_lay.setContentsMargins(0,0,0,0)
            self._add_bullet_section(gaps_lay, "Gaps identificados", analysis.get("gap_reason", ""), "fa5s.exclamation-circle", C.ACC2)
            cols.addWidget(gaps_widget)
            lay.addLayout(cols)
            
            # Red Flags
            red_flags = analysis.get("red_flags", [])
            if red_flags:
                self._add_red_flags_section(lay, red_flags)
                
            # Cover Letter Strategy
            self._add_section(lay, "Estratégia de Abordagem / Apply Assist", analysis.get("cover_letter_idea", ""), "fa5s.magic", C.ACC)
            
        else:
            lbl = QLabel("Esta vaga ainda não foi analisada. Aguarde a triagem inteligente.")
            lbl.setFont(QFont("Inter", 9))
            lbl.setStyleSheet(f"color: {C.TEXT_DIM};")
            lay.addWidget(lbl)
            
        # Description Raw toggle
        desc_btn = QPushButton(" Ver descrição completa da vaga")
        desc_btn.setFont(QFont("Inter", 8))
        desc_btn.setStyleSheet(f"color: {C.TEXT_MED}; text-align: left; background: transparent; border: none;")
        desc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        desc_box = QTextEdit()
        desc_box.setPlainText(job.get("description", ""))
        desc_box.setReadOnly(True)
        desc_box.setMaximumHeight(200)
        desc_box.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        desc_box.setStyleSheet(f"background: #080808; border: 1px solid {C.BORDER}; color: {C.TEXT_MED}; font-family: 'Inter'; font-size: 8px;")
        desc_box.hide()
        
        def toggle_desc():
            if desc_box.isHidden():
                desc_box.show()
                desc_btn.setText(" Ocultar descrição")
            else:
                desc_box.hide()
                desc_btn.setText(" Ver descrição completa da vaga")
                
        desc_btn.clicked.connect(toggle_desc)
        lay.addWidget(desc_btn)
        lay.addWidget(desc_box)
        
        scroll.setWidget(content)
        self.details_lay.addWidget(scroll)
        
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
        
    def _add_bullet_section(self, parent_layout, title: str, content: str, icon: str, color: str):
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
        
        t_lbl = QLabel(" PONTOS DE ALERTA (RED FLAGS)")
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
        dialog = ProfileDialog(self)
        if dialog.exec():
            # Refresh details if selected
            if self._selected_job:
                self.show_details(self._selected_job)
                
    def _open_job_url(self):
        if self._selected_job and self._selected_job.get("url"):
            url = self._selected_job.get("url")
            import webbrowser
            webbrowser.open(url)
            
            # Geração de cover letter automática para o clipboard (Apply Assist)
            try:
                analysis = self._selected_job.get("analysis", {})
                cv_tip = analysis.get("cover_letter_idea", "")
                
                # Gera uma cover letter básica baseada no cargo e no match para ajudar o usuário
                profile_path = Path(__file__).resolve().parent.parent / "config" / "user_profile.json"
                user_name = "Rafael Ildefonso"
                skills = []
                if profile_path.exists():
                    with open(profile_path, "r", encoding="utf-8") as f:
                        d = json.load(f)
                        user_name = d.get("full_name", user_name)
                        skills = d.get("skills", [])
                        
                cover_letter = (
                    f"Olá, recrutador(a).\n\n"
                    f"Meu nome é {user_name} e gostaria de demonstrar meu interesse na vaga de {self._selected_job.get('title')} na {self._selected_job.get('company')}.\n\n"
                    f"Acredito que meu perfil possui uma excelente sinergia com os requisitos exigidos, especialmente pela minha experiência prática com "
                    f"{', '.join(skills[:4])}.\n\n"
                    f"Estou à disposição para uma conversa detalhada sobre como minhas habilidades podem contribuir com a equipe.\n\n"
                    f"Atenciosamente,\n"
                    f"{user_name}"
                )
                
                from PyQt6.QtWidgets import QApplication
                clipboard = QApplication.clipboard()
                clipboard.setText(cover_letter)
                
                # Log on status or notification
                self.log_lbl.setText("Apply Assist: Carta de apresentação copiada para a área de transferência!")
                self.log_lbl.show()
                
            except Exception as e:
                print(f"[JobRadar] Erro no Apply Assist: {e}")
                
    def _on_filter_changed(self):
        self.load_jobs()

    def _start_scanning(self):
        # Fetch target roles from profile
        profile_path = Path(__file__).resolve().parent.parent / "config" / "user_profile.json"
        keywords = "Desenvolvedor Python"
        if profile_path.exists():
            try:
                with open(profile_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    roles = d.get("target_roles", [])
                    if roles:
                        keywords = roles[0] # Search first target role
            except:
                pass
                
        max_jobs = self.limit_spin.value() if hasattr(self, 'limit_spin') else 8
        sources = ["linkedin", "google_jobs"]
                
        # Start Worker thread
        self.progress_bar.show()
        self.log_lbl.setText(f"Iniciando Radar de Vagas (LinkedIn + Google Jobs) para '{keywords}'...")
        self.log_lbl.show()
        self.refresh_btn.setEnabled(False)
        
        self.worker = ScrapeWorker(keywords, max_jobs=max_jobs, sources=sources)
        self.worker.log_signal.connect(self._update_log)
        self.worker.finished.connect(self._scan_finished)
        self.worker.start()
        
    def _update_log(self, text: str):
        self.log_lbl.setText(text)
        
    def _scan_finished(self, total_new):
        self.progress_bar.hide()
        self.refresh_btn.setEnabled(True)
        if total_new >= 0:
            self.log_lbl.setText(f"Radar finalizado! {total_new} novas vagas encontradas (LinkedIn + Google Jobs).")
            self.load_jobs()
        else:
            self.log_lbl.setText("Erro ao executar busca automática. Verifique os logs do console.")
