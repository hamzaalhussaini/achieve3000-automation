import json
import os, sys, time, logging, re
from typing import List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from playwright.sync_api import sync_playwright, Page

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Achieve3000")

EXCLUDED  = ["Article Only", "Video", "Instruction + Activity", "Video Lesson"]
ALL_TYPES = ["2-Step Lesson", "5-Step Lesson", "Article Only", "Video", "Instruction + Activity",
             "Video Lesson", "Article + Activity", "Activity"]
MAX_AI_FAILURES = 5
AI_RETRY_DELAY_SECONDS = 5


class AIResponseError(RuntimeError):
    """Raised when the model cannot provide a usable response."""


class AI:
    def __init__(
        self,
        model="openai/gpt-oss-20b",
        endpoint="https://api.groq.com/openai/v1/chat/completions",
    ):
        self.model = model
        self.endpoint = endpoint
        self.api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if self.api_key:
            logger.info("Groq ready (%s)", model)
        else:
            logger.error("GROQ_API_KEY is not configured; AI responses are unavailable.")

    def ask(self, prompt: str, fallback: str = "", json_mode: bool = False) -> str:
        request_body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        # Do not use Groq provider-side JSON mode for openai/gpt-oss-20b.
        # That mode can reject an empty generation with HTTP 400 before the
        # local parser gets a chance to retry. The prompt and json.loads()
        # below still enforce the required schema.

        last_error = "unknown AI failure"
        for attempt in range(1, MAX_AI_FAILURES + 1):
            if not self.api_key:
                last_error = "GROQ_API_KEY is not configured"
            else:
                request = Request(
                    self.endpoint,
                    data=json.dumps(request_body).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "User-Agent": "achieve3000-automation/1.0",
                    },
                    method="POST",
                )
                try:
                    with urlopen(request, timeout=45) as response:
                        result = json.loads(response.read().decode("utf-8"))
                    content = (result["choices"][0]["message"]["content"] or "").strip()
                    if content:
                        return content
                    last_error = "Groq returned an empty response"
                except HTTPError as e:
                    details = e.read().decode("utf-8", errors="replace")
                    last_error = f"HTTP {e.code}: {details}"
                    logger.error("Groq attempt %d/%d failed: HTTP %d", attempt, MAX_AI_FAILURES, e.code)
                except (URLError, KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
                    last_error = str(e)
                    logger.error("Groq attempt %d/%d failed: %s", attempt, MAX_AI_FAILURES, e)
                except Exception as e:
                    last_error = str(e)
                    logger.error("Groq attempt %d/%d failed: %s", attempt, MAX_AI_FAILURES, e)

            if attempt < MAX_AI_FAILURES:
                logger.warning(
                    "No usable AI response; waiting %ss before retry %d/%d.",
                    AI_RETRY_DELAY_SECONDS, attempt + 1, MAX_AI_FAILURES,
                )
                time.sleep(AI_RETRY_DELAY_SECONDS)

        raise AIResponseError(
            f"AI failed {MAX_AI_FAILURES} consecutive times; stopping safely. Last error: {last_error}"
        )

    def _telemetry(self, payload: str) -> None:
        payload_length = len(payload)
        print(f"[TELEMETRY] scraped_article_chars={payload_length}", flush=True)
        if payload_length < 150:
            logger.warning(
                "[TELEMETRY WARNING] scraped article payload is below 150 characters "
                "(%d chars)", payload_length
            )

    def mcq(self, article: str, question: str, choices: List[str]) -> str:
        if not choices:
            return ""

        article_payload = article[:3000]
        self._telemetry(article_payload)
        options = "\n".join(f"- {choice}" for choice in choices[:4])
        prompt = (
            f"ARTICLE:\n{article_payload}\n\n"
            f"QUESTION:\n{question}\n\n"
            f"OPTIONS:\n{options}\n\n"
            "Select the correct option. Return raw JSON only, with exactly this schema "
            '{"selected_option_exact_text": "string"}. '
            "The value must be the exact text of one option. Do not use markdown fences, "
            "additional keys, explanations, or option letters."
        )
        for attempt in range(1, MAX_AI_FAILURES + 1):
            raw = self.ask("\n".join([prompt, "Return only the required JSON object." ]), json_mode=True)
            cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.IGNORECASE)
            try:
                parsed = json.loads(cleaned)
                selected = parsed["selected_option_exact_text"]
                if not isinstance(selected, str) or not selected.strip():
                    raise ValueError("selected_option_exact_text must be a non-empty string")
                return selected.strip()
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.warning("Invalid Groq MCQ JSON response (%d/%d): %s", attempt, MAX_AI_FAILURES, exc)
                if attempt < MAX_AI_FAILURES:
                    time.sleep(AI_RETRY_DELAY_SECONDS)
        raise AIResponseError("AI returned invalid MCQ JSON five consecutive times; stopping safely.")

    def agree(self, statement: str, article: str) -> bool:
        article_payload = article[:2000]
        self._telemetry(article_payload)
        prompt = (f"Article:\n{article_payload}\n\nStatement: {statement}\n\n"
                  f"Should a student AGREE or DISAGREE? Reply with exactly: AGREE or DISAGREE.")
        return "DISAGREE" not in self.ask(prompt, "AGREE").upper()

    def write_answer(self, question: str, article: str) -> str:
        article_payload = article[:2000]
        self._telemetry(article_payload)
        prompt = (f"ARTICLE:\n{article_payload}\n\nQUESTION:\n{question}\n\n"
                  f"Write a direct 2-4 sentence student answer. Write naturally, no preamble.")
        return self.ask(prompt, "This article provided useful and interesting information about the topic.")


class Bot:
    def __init__(self, url="https://portal.achieve3000.com",
                 user=None, pw=None,
                 iters=None, rebuild=None):
        self.url     = url.rstrip("/")
        self.user    = user if user is not None else os.environ.get("ACHIEVE3000_USERNAME", "")
        self.pw      = pw if pw is not None else os.environ.get("ACHIEVE3000_PASSWORD", "")
        self.iters   = int(iters if iters is not None else os.environ.get("ITERATIONS", "40"))
        self.rebuild = int(rebuild if rebuild is not None else os.environ.get("REBUILD_EVERY", "5"))
        if self.iters < 1:
            raise ValueError("ITERATIONS must be at least 1")
        if self.rebuild < 1:
            raise ValueError("REBUILD_EVERY must be at least 1")
        self.ai      = AI()
        self.playwright = self.browser = self.ctx = self.page = None

    def init(self):
        # Packaged builds use the Chromium folder shipped beside the EXE.
        # Normal Python runs continue using Playwright's standard browser path.
        if getattr(sys, "frozen", False):
            bundled_browsers = os.path.join(
                os.path.dirname(sys.executable), "playwright-browsers"
            )
            if os.path.isdir(bundled_browsers):
                os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled_browsers
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=os.environ.get("HEADLESS", "false").strip().lower() in {"1", "true", "yes", "on"},
            args=["--disable-dev-shm-usage", "--no-sandbox"])
        self._new_ctx()

    def _new_ctx(self):
        if self.ctx:
            try: self.ctx.close()
            except: pass
        self.ctx = self.browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"))
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(15000)
        logger.info("Context rebuilt.")

    def close(self):
        if self.ctx:
            try: self.ctx.close()
            except Exception: pass
        if self.browser:
            try: self.browser.close()
            except Exception: pass
        if self.playwright:
            try: self.playwright.stop()
            except Exception: pass

    def s(self, t): time.sleep(t)

    @staticmethod
    def _option_key(text: str) -> str:
        """Normalize only the rendered A./B./C./D. label prefix."""
        text = re.sub(r"^\s*[A-Da-d]\s*[.)\-:]\s*", "", text or "")
        return " ".join(text.split()).casefold()

    def clk(self, loc) -> bool:
        try: loc.click(); return True
        except:
            try: loc.click(force=True); return True
            except: return False

    def article(self) -> str:
        """Extract article text through the split-pane fallback tree."""
        self.dismiss()
        selectors = [
            ".article-content",
            ".article-body",
            "#article-text",
            ".reading-panel",
            "div[class*='article']",
        ]
        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                if locator.count() == 0:
                    continue
                text = locator.first.inner_text(timeout=1500).strip()
                if text:
                    logger.info("Article extraction selector=%s chars=%d", selector, len(text))
                    return text
            except Exception as exc:
                logger.debug("Article selector %s failed: %s", selector, exc)

        try:
            text = self.page.locator("body").inner_text(timeout=3000).strip()
            logger.info("Article extraction selector=body chars=%d", len(text))
            return text
        except Exception as exc:
            logger.warning("Article body fallback failed: %s", exc)
            return ""

    def question(self) -> str:
        try:
            self.dismiss()
            return self.page.evaluate("""() => {
                const e = document.querySelector(
                    '#activity-component-react, #question-text, [data-testid="question-text"]');
                return e ? e.textContent.trim() : '';
            }""")
        except: return ""

    def dismiss(self):
        """Clear floating close actions and dismiss overlays before reading text."""
        for s in [
            ".ui-dialog-titlebar-close",
            "button[aria-label='Close']", "button[aria-label='close']",
            "button[title='Close']",      "button[title='close']",
            "button:text-is('X')",        "button:text-is('\u00d7')",
            ".modal .close",              "[data-testid='modal-close']",
        ]:
            try:
                l = self.page.locator(s).first
                if l.is_visible(timeout=300): l.click(force=True); self.s(0.4)
            except: pass
        try:
            self.page.evaluate("""() => {
                const closeSelectors = [
                    'button[aria-label*="close" i]', 'a[aria-label*="close" i]',
                    'button[title*="close" i]', 'a[title*="close" i]',
                    '[data-testid*="close" i]', '.ui-dialog-titlebar-close',
                    '.modal .close', '.modal-close', '.close-button'
                ];
                const closeNodes = [...document.querySelectorAll(closeSelectors.join(','))];
                for (const node of document.querySelectorAll('button, a, [role="button"]')) {
                    const text = (node.textContent || '').trim();
                    if (text === 'X' || text === '\u00d7' || text === 'x') closeNodes.push(node);
                }
                for (const node of [...new Set(closeNodes)]) {
                    try { node.click(); } catch (e) {}
                    const overlay = node.closest(
                        '[role="dialog"], .modal, .overlay, .MuiDialog-root, .ui-dialog, ' +
                        '.modal-backdrop, .MuiBackdrop-root'
                    );
                    if (overlay && overlay !== document.body) {
                        try { overlay.remove(); } catch (e) {}
                    }
                }
            }""")
            self.s(0.3)
        except: pass

    def fill(self, text: str) -> bool:
        try:
            r = self.page.evaluate("""(t) => {
                const f = document.querySelector('.tox-edit-area__iframe');
                if (f) {
                    const d = f.contentDocument || f.contentWindow.document;
                    if (d && d.body) {
                        d.body.innerHTML = t;
                        setTimeout(() => {
                            d.body.innerHTML += ' ';
                            d.body.dispatchEvent(new Event('input', {bubbles:true}));
                        }, 200);
                        return 'iframe';
                    }
                }
                if (window.tinymce && window.tinymce.editors && window.tinymce.editors.length) {
                    window.tinymce.editors.forEach(e => { e.setContent(t); e.save(); });
                    return 'tinymce';
                }
                const ta = document.querySelector('textarea');
                if (ta) {
                    const nv = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
                    if (nv && nv.set) nv.set.call(ta, t); else ta.value = t;
                    ta.dispatchEvent(new Event('input',  {bubbles:true}));
                    ta.dispatchEvent(new Event('change', {bubbles:true}));
                    return 'textarea';
                }
                const ce = document.querySelector('[contenteditable="true"]');
                if (ce) {
                    ce.focus();
                    const sel = window.getSelection();
                    const range = document.createRange();
                    range.selectNodeContents(ce);
                    sel.removeAllRanges(); sel.addRange(range);
                    try {
                        document.execCommand('insertText', false, t);
                        return 'ce-exec';
                    } catch(e) {
                        ce.innerHTML = t;
                        ce.dispatchEvent(new Event('input', {bubbles:true}));
                        return 'ce-fallback';
                    }
                }
                return 'none';
            }""", text)
            logger.info(f"fill via {r}")
            return r != "none"
        except Exception as e:
            logger.warning(f"fill err: {e}"); return False

    def wait_for_editor(self, timeout=6) -> bool:
        for _ in range(timeout * 2):
            found = self.page.evaluate("""() => !!(
                document.querySelector('.tox-edit-area__iframe') ||
                (window.tinymce && window.tinymce.editors && window.tinymce.editors.length) ||
                document.querySelector('textarea') ||
                document.querySelector('[contenteditable="true"]')
            )""")
            if found: return True
            self.s(0.5)
        return False

    def submit_btn(self) -> bool:
        try:
            for b in self.page.locator("button").all():
                try:
                    if b.text_content(timeout=400).strip() == "Submit":
                        self.clk(b); return True
                except: pass
        except: pass
        return False

    def handle_info_dialog(self, wait_seconds: float = 3.0) -> bool:
        """Dismiss any visible OK/confirmation dialog across all lesson steps."""
        selectors = [
            "[role='dialog'] button:has-text('OK')",
            "[role='alertdialog'] button:has-text('OK')",
            "button:has-text('OK')",
            "input[value='OK']",
            ".ui-dialog-buttonpane button:has-text('OK')",
        ]
        attempts = max(1, int(wait_seconds / 0.25))
        for _ in range(attempts):
            for selector in selectors:
                try:
                    button = self.page.locator(selector).first
                    if button.is_visible(timeout=250):
                        self.clk(button)
                        self.s(0.4)
                        logger.info("Dismissed information dialog: %s", selector)
                        return True
                except Exception:
                    pass
            self.s(0.25)
        return False

    def _radio_is_selected(self, radio) -> bool:
        try:
            aria_checked = (radio.get_attribute("aria-checked") or "").lower()
            if aria_checked == "true":
                return True
            return bool(radio.evaluate("""el => {
                if (el.matches('input[type="radio"]')) return el.checked;
                const input = el.querySelector('input[type="radio"]');
                return !!(input && input.checked);
            }"""))
        except Exception:
            return False

    def _ensure_radio_selected(self, radio, literal_text: str) -> bool:
        """Retry only the requested literal option and verify selection."""
        for attempt in range(1, 4):
            if radio is None:
                return False
            try:
                radio.click(timeout=2000)
            except Exception:
                try:
                    radio.click(force=True, timeout=2000)
                except Exception:
                    pass
            self.s(0.2)
            if self._radio_is_selected(radio):
                return True

            # Some portal versions attach the click handler to the text span
            # rather than the role=radio node. Retry that same exact text.
            try:
                text_target = self.page.get_by_text(literal_text, exact=True).first
                text_target.click(force=True, timeout=1000)
                self.s(0.2)
                if self._radio_is_selected(radio):
                    return True
            except Exception:
                pass
            logger.warning("Exact option selection attempt %d/3 failed: %s", attempt, literal_text)
        return False

    def next_btn(self) -> bool:
        """Click any forward-navigation button. Tries many label variants."""
        self.handle_info_dialog()
        self.dismiss()
        candidates = [
            "button:has-text('Next')",
            "a:has-text('Next')",
            "input[value='Next']",
            "button:has-text('Continue')",
            "a:has-text('Continue')",
            "button:has-text('Start Activity')",
            "button:has-text('Begin')",
            "button:has-text('Done')",
            "button:has-text('Finish')",
            "button:has-text('Submit')",
        ]
        for s in candidates:
            try:
                l = self.page.locator(s).first
                if l.is_visible(timeout=800):
                    logger.info(f"  next_btn clicked: {s}")
                    clicked = self.clk(l)
                    if clicked:
                        self.s(0.3)
                        self.handle_info_dialog()
                        self.dismiss()
                    return clicked
            except: pass
        return False

    def _scroll_reading_to_end(self):
        """Reveal bottom-of-article controls inside either the page or reader."""
        try:
            self.page.evaluate("""() => {
                const roots = [
                    document.querySelector('#start-reading'),
                    document.querySelector('[role="main"]'),
                    document.scrollingElement
                ].filter(Boolean);
                for (const r of roots) {
                    try { r.scrollTop = r.scrollHeight; } catch (e) {}
                }
                window.scrollTo(0, document.body.scrollHeight);
            }""")
            self.s(0.5)
        except Exception as e:
            logger.debug(f"  reader scroll failed: {e}")

    def _read_advance(self) -> bool:
        """Click the most likely read-page advance control.

        Read pages sometimes use an icon-only button or an anchor to the next
        activity, neither of which is covered by the generic next_btn helper.
        """
        self.dismiss()
        self._scroll_reading_to_end()
        candidates = [
            "a[href*='/lesson/respond']",
            "a[href*='/activity']",
            "button[data-testid*='next' i]",
            "a[data-testid*='next' i]",
            "[aria-label*='next page' i]",
            "[aria-label*='next activity' i]",
            "[aria-label='Next' i]",
            "button[title*='next' i]",
            "a[title*='next' i]",
            "button:has-text('Activity')",
            "a:has-text('Activity')",
            "button:has-text('Next')",
            "a:has-text('Next')",
            "input[value='Next']",
            "button:has-text('Continue')",
            "a:has-text('Continue')",
        ]
        for selector in candidates:
            try:
                loc = self.page.locator(selector).first
                if not loc.is_visible(timeout=500):
                    continue
                disabled = loc.get_attribute('disabled')
                aria_disabled = loc.get_attribute('aria-disabled')
                if disabled is not None or aria_disabled == 'true':
                    continue
                logger.info(f"  read advance clicked: {selector}")
                if self.clk(loc):
                    return True
            except Exception:
                pass

        # Last resort for icon-only controls: inspect visible buttons/links and
        # use their accessible name, title, or href instead of brittle classes.
        try:
            clicked = self.page.evaluate("""() => {
                const els = [...document.querySelectorAll('button, a, input')];
                const re = /(next|continue|activity|finish|done|right)/i;
                const el = els.find(e => {
                    const s = [e.innerText, e.getAttribute('aria-label'),
                               e.getAttribute('title'), e.getAttribute('value'),
                               e.getAttribute('href')].filter(Boolean).join(' ');
                    const r = e.getBoundingClientRect();
                    return re.test(s) && r.width > 0 && r.height > 0 &&
                           getComputedStyle(e).visibility !== 'hidden' &&
                           e.getAttribute('aria-disabled') !== 'true';
                });
                if (!el) return false;
                el.click();
                return true;
            }""")
            if clicked:
                logger.info("  read advance clicked via accessible-name fallback")
                return True
        except Exception:
            pass
        return False

    # ── Login ──────────────────────────────────
    def login(self):
        if not self.user or not self.pw:
            raise RuntimeError(
                "Set ACHIEVE3000_USERNAME and ACHIEVE3000_PASSWORD in the environment or .env file."
            )
        logged_in_paths = ["/home", "/my_lessons", "/lesson"]
        if any(p in self.page.url for p in logged_in_paths):
            logger.info("Already logged in."); return
        # Keep an existing authenticated session out of /index during recovery.
        try:
            self.page.goto(f"{self.url}/home", wait_until="networkidle")
            if any(p in self.page.url for p in logged_in_paths):
                self.page.goto(f"{self.url}/my_lessons", wait_until="networkidle")
                logger.info("Session recovered via /home; at /my_lessons.")
                return
        except Exception:
            pass
        logger.info("Logging in...")
        self.page.goto(f"{self.url}/index", wait_until="networkidle")
        try: self.page.locator("#login_name1,input[name='login_name1']").first.fill(self.user)
        except: pass
        try: self.page.locator("#password1,input[name='password1']").first.fill(self.pw)
        except: pass
        self.page.evaluate("""() => {
            const ln=document.getElementById('login_name'), ln1=document.getElementById('login_name1');
            if(ln&&ln1) ln.value=ln1.value;
            const pw=document.getElementById('password'), pw1=document.getElementById('password1');
            if(pw&&pw1) pw.value=pw1.value;
            if(typeof submitForm==='function') submitForm();
            else { const f=document.querySelector('form'); if(f) f.submit(); }
        }""")
        self.s(2); self.page.wait_for_load_state("networkidle"); self.s(1.5)
        school_or_home = self.page.get_by_text(
            re.compile(r"^\s*(?:In\s+)?(?:School|Home)\s*$", re.IGNORECASE)
        ).first
        try:
            if school_or_home.is_visible(timeout=1500):
                logger.info("Login transition marker detected: %s", school_or_home.inner_text().strip())
                school = self.page.get_by_text(
                    re.compile(r"^\s*(?:In\s+)?School\s*$", re.IGNORECASE)
                ).first
                if school.is_visible(timeout=1500):
                    self.clk(school)
                    logger.info("Clicked School")
        except Exception:
            pass
        self.s(2)
        for continue_selector in [
            "input[value='Continue']",
            "button:has-text('Continue')",
            "a:has-text('Continue')",
        ]:
            try:
                l = self.page.locator(continue_selector).first
                if l.is_visible(timeout=1500):
                    self.clk(l)
                    self.page.wait_for_load_state("networkidle")
                    self.s(1.5)
                    break
            except Exception:
                pass
        self.page.goto(f"{self.url}/my_lessons", wait_until="networkidle")
        logger.info("At /my_lessons.")

    # ── Select lesson → returns (clicked, lesson_type) ──
    def select(self):
        self.s(2)
        seen: set = set()
        processed: set = set()
        lesson_number = 0

        stalled_passes = 0
        empty_scans = 0
        for scroll_pass in range(1, 9):
            self.dismiss()
            links = []
            for lnk in self.page.locator("a[href*='/lesson?lid=']").all():
                try:
                    href = lnk.get_attribute("href") or ""
                    if href and href not in seen:
                        seen.add(href)
                        links.append(lnk)
                except Exception:
                    pass
            logger.info(
                "Lesson scan %d/8: %d new links (%d total)",
                scroll_pass, len(links), len(seen),
            )
            if links:
                empty_scans = 0
            else:
                empty_scans += 1

            for lnk in links:
                try:
                    href = lnk.get_attribute("href") or ""
                    if href in processed:
                        continue
                    processed.add(href)
                    lesson_number += 1
                    m = re.search(r"lid=(\d+)", href)
                    lid = m.group(1) if m else ""

                    lesson_type = self.page.evaluate("""(lid) => {
                        const TYPES = ["2-Step Lesson","5-Step Lesson","Article Only","Video",
                                       "Instruction + Activity","Video Lesson",
                                       "Article + Activity","Activity"];
                        const exactType = document.querySelector(
                            `[data-testid="lesson-type-${lid}"], #lesson-type-${lid}`
                        );
                        if (exactType) return (exactType.innerText || exactType.textContent || '').trim();
                        const chip = document.querySelector(
                            '[data-testid="mobile-lesson-chip-type-' + lid + '"]');
                        if (chip) return chip.getAttribute('aria-label') || chip.innerText || '';
                        const link = document.querySelector('a[href*="lid=' + lid + '"]');
                        if (!link) return '';
                        let node = link;
                        for (let d = 0; d < 20; d++) {
                            if (!node.parentElement) break;
                            node = node.parentElement;
                            const tag    = node.tagName;
                            const testid = node.getAttribute('data-testid') || '';
                            const role   = node.getAttribute('role') || '';
                            const txt = (node.innerText || '').replace(/\\s+/g, ' ');
                            for (const t of TYPES) { if (txt.includes(t)) return t; }
                        }
                        return '';
                    }""", lid)

                    logger.info(f"  #{lesson_number} lid={lid} type='{lesson_type}'")
                    if any(ex.lower() in lesson_type.lower() for ex in EXCLUDED):
                        logger.info(f"  Skip #{lesson_number}: excluded ({lesson_type})"); continue
                    if lesson_type == "":
                        logger.info(f"  Skip #{lesson_number}: unknown type (safety skip)"); continue

                    label = lnk.inner_text().strip()[:60]
                    logger.info(f"  Clicking #{lesson_number}: '{label}' [{lesson_type}]")
                    self.clk(lnk); self.page.wait_for_load_state("networkidle"); self.s(2)
                    return True, lesson_type
                except Exception as e:
                    logger.warning(f"  Link #{lesson_number} error: {e}")

            if empty_scans >= 2 and stalled_passes >= 2:
                logger.info("No new lesson links and the lesson grid has stopped moving; stopping safely.")
                break

            scroll_result = self.page.evaluate("""() => {
                const preferred = document.querySelector(
                    '.MuiDataGrid-virtualScroller, [class*="MuiDataGrid-virtualScroller"]'
                );
                const candidates = [...document.querySelectorAll('*')]
                    .filter(el => {
                        const rect = el.getBoundingClientRect();
                        const style = getComputedStyle(el);
                        const name = `${el.id} ${el.className || ''} ${el.getAttribute('data-testid') || ''}`;
                        return el !== document.body &&
                            el.scrollHeight > el.clientHeight + 20 &&
                            el.clientHeight > 120 && el.clientWidth > 250 &&
                            rect.width > 250 && rect.height > 120 &&
                            rect.bottom > 0 && rect.top < window.innerHeight &&
                            style.display !== 'none' && style.visibility !== 'hidden' &&
                            el.querySelector('a[href*="/lesson?lid="]') &&
                            (/(auto|scroll)/.test(style.overflowY) ||
                             /(lesson|grid|table|list|dashboard)/i.test(name));
                    })
                    .sort((a, b) => {
                        const score = el => {
                            const name = `${el.id} ${el.className || ''} ${el.getAttribute('data-testid') || ''}`;
                            return (/(lesson|grid|table|list|dashboard)/i.test(name) ? 1000000 : 0) +
                                el.scrollHeight - el.clientHeight;
                        };
                        return score(b) - score(a);
                    });
                const container = preferred && preferred.scrollHeight > preferred.clientHeight + 20
                    ? preferred : candidates[0];

                if (!container) {
                    return {moved: false, bottom: true, target: 'lesson-grid-not-found'};
                }

                if (container) {
                    const before = container.scrollTop;
                    const amount = Math.max(container.clientHeight * 0.55, 400);
                    container.scrollTop = Math.min(
                        before + amount,
                        container.scrollHeight - container.clientHeight
                    );
                    return {
                        moved: container.scrollTop > before,
                        bottom: container.scrollTop + container.clientHeight >= container.scrollHeight - 5,
                        target: `${container.tagName}.${container.className || ''}`
                    };
                }

            }""")
            logger.info("Lesson scroll target=%s moved=%s bottom=%s",
                        scroll_result["target"], scroll_result["moved"], scroll_result["bottom"])
            self.s(1.2)
            if scroll_result["moved"]:
                stalled_passes = 0
            else:
                stalled_passes += 1
            # A candidate reaching its bottom does not prove the virtualized
            # lesson list is exhausted; continue until two scans cannot move.
            if stalled_passes >= 2:
                break

        logger.error("No valid lesson found."); return False, ""

    # ── Shared: read article pages ──────────────
    def _read_pages(self):
        """
        Navigate all article pages.
        For single-page articles: dismiss modal, scroll, done.
        For multi-page articles: keep clicking Next until the URL leaves /lesson/read.
        Returns when we've left the read page OR exhausted retries.
        """
        logger.info("[Read] Navigating article pages...")
        self.s(1.5); self.dismiss()

        # Try explicit tab/pagination links first (numbered pages)
        tabs = self.page.locator(".page-tab, [data-page], .pagination a").all()
        if len(tabs) > 1:
            logger.info(f"  Found {len(tabs)} page tabs.")
            for t in tabs:
                try:
                    if t.is_visible(timeout=400):
                        self.clk(t); self.s(1.2); self.dismiss()
                except: pass
            # After clicking all tabs, still need to hit Next to leave /read

        # Keep advancing until the URL changes away from /lesson/read.  A
        # click that leaves the URL unchanged is not necessarily a failure on
        # the first attempt (React may still be rendering), but repeated
        # unchanged clicks indicate a blocked or missing control.
        unchanged = 0
        last_url = self.page.url
        for page_num in range(1, 25):
            cur = self.page.url
            if "/lesson/read" not in cur:
                logger.info(f"  Left /lesson/read after page {page_num-1} — done.")
                return   # Already navigated away; caller doesn't need to click Next again
            logger.info(f"  Article page {page_num}: clicking forward...")
            clicked = self._read_advance()
            if not clicked:
                unchanged += 1
                logger.info(f"  No read advance control found ({unchanged}/3).")
            else:
                try: self.page.wait_for_load_state("networkidle", timeout=5000)
                except: pass
                self.s(1.2)

                new_url = self.page.url
                if new_url == last_url:
                    unchanged += 1
                    logger.info(f"  Read URL unchanged after click ({unchanged}/3).")
                else:
                    unchanged = 0
                    last_url = new_url

            if "/lesson/read" not in self.page.url:
                logger.info("  Read navigation succeeded.")
                return
            if unchanged >= 3:
                logger.warning("  Read navigation made no progress after 3 attempts; stopping safely.")
                return

        logger.info("  _read_pages done.")

    # ── Shared: MCQ loop ────────────────────────
    def _answer_mcq_loop(self):
        logger.info("[MCQ] Answering questions...")
        for n in range(1, 20):
            self.dismiss()
            radios = self.page.locator('[role="radio"]').all()
            if not radios:
                logger.info(f"  No radios at Q{n} — done."); return True

            art     = self.article()
            q       = self.question()
            choices = []
            for r in radios[:4]:
                try:    choices.append(r.text_content(timeout=400).strip() or f"Opt{len(choices)+1}")
                except: choices.append(f"Opt{len(choices)+1}")
            logger.info(f"  Q{n}: {q[:70]}")
            logger.info(f"  choices: {choices}")

            selected_text = self.ai.mcq(art, q, choices)
            logger.info("  -> selected option: %s", selected_text)

            # Match the literal option text against the rendered radio itself.
            # get_by_role(name=...) is unreliable here because the portal may
            # build the accessible name from hidden spans or an answer prefix.
            selected_radio = None
            selected_index = 0
            normalized_selected = self._option_key(selected_text)
            selected_rendered_text = selected_text
            for option_index, (radio, choice_text) in enumerate(zip(radios[:4], choices[:4])):
                normalized_choice = self._option_key(choice_text)
                if normalized_choice == normalized_selected:
                    selected_radio = radio
                    selected_index = option_index
                    selected_rendered_text = choice_text
                    break

            clicked = False
            if selected_radio is not None:
                clicked = self._ensure_radio_selected(selected_radio, selected_rendered_text)

            if not clicked:
                logger.warning(
                    "Could not select model-selected option after exact retries; "
                    "Submit was not clicked: %s", selected_text
                )
                self.handle_info_dialog()
                return False
            self.s(0.4)

            if not self.submit_btn():
                logger.info("  No Submit — stopping."); break
            self.page.wait_for_load_state("networkidle"); self.s(1.0)
            self.handle_info_dialog()

            # Feedback / retry: when the model is unavailable or wrong, use the
            # portal's own Try again state and cycle literal rendered options.
            try:
                fb = self.page.locator("#feedbackActivityFormBtn").first
                if fb.is_visible(timeout=1200):
                    fb_txt = fb.text_content(timeout=400).strip()
                    logger.info(f"  feedback: '{fb_txt}'")
                    retry_count = 0
                    while fb_txt.casefold() == "try again" and retry_count < 4:
                        self.clk(fb)
                        self.s(1.0)
                        rr = self.page.locator('[role="radio"]').all()
                        if not rr:
                            break

                        retry_index = (selected_index + retry_count + 1) % min(len(rr), 4)
                        try:
                            rr[retry_index].click(force=True, timeout=2000)
                        except Exception as exc:
                            logger.warning("Retry option click failed: %s", exc)
                            break
                        self.s(0.4)
                        if not self.submit_btn():
                            break
                        self.page.wait_for_load_state("networkidle")
                        self.s(1.0)
                        retry_count += 1

                        fb = self.page.locator("#feedbackActivityFormBtn").first
                        if not fb.is_visible(timeout=1000):
                            break
                        fb_txt = fb.text_content(timeout=400).strip()
                        logger.info("  retry %d feedback: '%s'", retry_count, fb_txt)

                    if fb_txt.casefold() != "try again":
                        self.clk(fb)
                        self.s(1.2)
            except Exception as e: logger.warning(f"  feedback err: {e}")

            if "/respond" not in self.page.url and "/activity" not in self.page.url:
                logger.info("  Left MCQ page."); break
        self.s(0.5)
        return True

    # ── Shared: Ready/Reflect poll + text ───────
    def _do_poll_and_text(self, step_name: str):
        logger.info(f"[{step_name}]")
        self.s(1.5); self.dismiss()

        has_poll = self.page.evaluate("""() => {
            const p = document.querySelector('#before-reading-poll');
            return p && p.querySelectorAll('input[type="radio"]').length > 0;
        }""")

        if has_poll:
            # smART XPaths for the poll question and radios
            q = self.page.evaluate("""() => {
                try {
                    const x = document.evaluate(
                        '//*[@id="before-reading-poll"]/div[1]/p[2]/div',
                        document, null, XPathResult.STRING_TYPE, null);
                    if (x.stringValue) return x.stringValue.trim();
                } catch(e) {}
                const f = document.querySelector('#before-reading-poll p:nth-of-type(2) div')
                       || document.querySelector('#before-reading-poll p div');
                return f ? f.textContent.trim() : '';
            }""")
            logger.info(f"  poll Q: {q[:80]}")
            agree = True
            logger.info("  Poll response: AGREE (fixed response; no Groq call)")

            xpath = ('//*[@id="before-reading-poll"]/div[1]/fieldset/div/label[{}]'
                     '/span[1]/input').format(1 if agree else 2)
            try: self.page.locator(f"xpath={xpath}").first.click()
            except:
                try: self.page.locator('input[type="radio"]').first.click()
                except: pass
            self.s(0.4)

            starter = "I agree because" if agree else "I disagree because"
            just = f"{starter} the topic is relevant and connected to the article."
            logger.info(f"  justification: {just[:60]}")
            self.wait_for_editor(timeout=5)
            self.fill(just); self.s(0.5)
            self.submit_btn(); self.s(1.5)
        else:
            ans = "The article was informative and provided useful details."
            logger.info(f"  writing (no poll): {ans[:60]}")
            self.wait_for_editor(timeout=5)
            self.fill(ans); self.s(0.5)
            self.submit_btn(); self.s(1.5)

    # ════════════════════════════════════════════
    # LESSON TYPE A — 2-Step Lesson / Article + Activity
    #   Flow: READ → MCQ (respond page)
    #   No Ready, no Reflect, no Write
    # ════════════════════════════════════════════
    def lesson_two_step(self):
        logger.info("=== 2-Step Lesson flow (Article + Activity) ===")
        url = self.page.url
        logger.info(f"  Starting URL: {url}")

        # ── READ ──────────────────────────────────
        if "/lesson/read" in url or "/lesson" in url:
            self._read_pages()   # leaves /lesson/read internally when it can
            logger.info(f"  After _read_pages URL: {self.page.url}")
            # Only click Next here if we're STILL on /read (e.g. no Next button found inside)
            if "/lesson/read" in self.page.url:
                logger.info("  Still on read — trying specialized read advance once more.")
                self._read_advance()
                try: self.page.wait_for_load_state("networkidle", timeout=5000)
                except: pass
                self.s(1.5)
                logger.info(f"  After extra next URL: {self.page.url}")

        # ── MCQ / ACTIVITY ────────────────────────
        stuck_on_read = 0
        for attempt in range(15):
            cur = self.page.url
            logger.info(f"  MCQ loop #{attempt+1} URL: {cur}")
            if "/my_lessons" in cur or "/lesson" not in cur:
                logger.info("  Reached non-lesson page — stopping."); break
            if "/lesson/read" in cur:
                stuck_on_read += 1
                logger.info(f"  Still on read page — attempting specialized advance ({stuck_on_read}/2).")
                before = self.page.url
                self._read_advance()
                try: self.page.wait_for_load_state("networkidle", timeout=5000)
                except: pass
                self.s(1.5)
                if self.page.url == before and stuck_on_read >= 2:
                    logger.error("  Could not leave /lesson/read after bounded retries; aborting this lesson.")
                    break
                continue
            stuck_on_read = 0
            had_radios = self.page.evaluate(
                "() => document.querySelectorAll('[role=\"radio\"]').length > 0")
            if had_radios:
                if not self._answer_mcq_loop():
                    logger.error("MCQ option could not be selected; leaving lesson without submitting a blank answer.")
                    return False
            else:
                logger.info("  No radios on this page — skipping MCQ.")
            clicked = self.next_btn()
            self.page.wait_for_load_state("networkidle"); self.s(1.5)
            if not clicked:
                logger.info("  No next button — lesson complete."); break

        logger.info("=== 2-Step Lesson complete ===")
        return True

    def lesson_article_activity(self):
        """Backward-compatible name for the two-step lesson flow."""
        return self.lesson_two_step()

    # ════════════════════════════════════════════
    # LESSON TYPE B — 5-Step Lesson
    #   Flow: READY → READ → RESPOND → REFLECT → WRITE
    # ════════════════════════════════════════════
    def lesson_five_step(self):
        logger.info("=== 5-Step Lesson flow ===")
        completed = True
        url = self.page.url

        steps = ["/lesson/ready", "/lesson/read", "/lesson/respond",
                 "/lesson/reflect", "/lesson/write"]
        start = 0
        for i, s in enumerate(steps):
            if s in url: start = i; break

        for step in steps[start:]:
            logger.info(f"\n--- {step.split('/')[-1].upper()} ---")
            try:
                if step == "/lesson/ready":
                    self._do_poll_and_text("Ready")
                    self.next_btn(); self.page.wait_for_load_state("networkidle"); self.s(1.5)

                elif step == "/lesson/read":
                    self._read_pages()
                    self.next_btn(); self.page.wait_for_load_state("networkidle"); self.s(1.5)

                elif step == "/lesson/respond":
                    self.s(1.5); self.dismiss()
                    if not self._answer_mcq_loop():
                        logger.error("MCQ option could not be selected; stopping this lesson safely.")
                        completed = False
                        break
                    self.next_btn(); self.page.wait_for_load_state("networkidle"); self.s(1.5)

                elif step == "/lesson/reflect":
                    self._do_poll_and_text("Reflect")
                    self.next_btn(); self.page.wait_for_load_state("networkidle"); self.s(1.5)

                elif step == "/lesson/write":
                    logger.info("[Write]")
                    self.s(1.5); self.dismiss()
                    q   = self.question()
                    art = self.article()
                    resp = (self.ai.write_answer(q, art) if q
                            else "This article provided useful and interesting information about the topic.")
                    logger.info(f"  writing: {resp[:60]}")
                    self.wait_for_editor(timeout=6)
                    self.fill(resp); self.s(1)
                    done = False
                    for sel in ["button:has-text('Finish')", "button:has-text('Done')",
                                "button:has-text('Submit')", "input[value='Submit']"]:
                        try:
                            l = self.page.locator(sel).first
                            if l.is_visible(timeout=1200): self.clk(l); done = True; break
                        except: pass
                    if not done: done = self.submit_btn()
                    if not done:
                        logger.error("Write response was not submitted; stopping this lesson safely.")
                        completed = False
                        break
                    self.page.wait_for_load_state("networkidle"); self.s(1.0)
                    self.handle_info_dialog()
                    self.next_btn()
                    self.page.wait_for_load_state("networkidle"); self.s(1.0)

            except AIResponseError:
                raise
            except Exception as e:
                logger.error(f"{step} error: {e}")
                completed = False
                self.s(2)

        logger.info("=== 5-Step complete ===")
        return completed

    # ── Dispatcher ─────────────────────────────
    def lesson(self, lesson_type: str):
        lt = lesson_type.lower()
        if "2-step" in lt or "article + activity" in lt or lt == "activity":
            return self.lesson_two_step()
        elif "5-step" in lt:
            return self.lesson_five_step()
        else:
            logger.info(f"Unknown type '{lesson_type}' — using 5-step fallback.")
            return self.lesson_five_step()

    # ── Main loop ──────────────────────────────
    def run(self):
        logger.info(f"=== {self.iters}-iter suite ===")
        if not self.user or not self.pw:
            raise RuntimeError(
                "Set ACHIEVE3000_USERNAME and ACHIEVE3000_PASSWORD in the environment or .env file."
            )
        ok = fail = 0
        try:
            self.init()
            for i in range(1, self.iters + 1):
                logger.info(f"\n{'='*50}\n  ITER {i}/{self.iters}\n{'='*50}")
                if i > 1 and (i - 1) % self.rebuild == 0: self._new_ctx()
                try:
                    self.login()
                    clicked, lesson_type = self.select()
                    if not clicked:
                        fail += 1
                        logger.error("No eligible lesson found; retrying in the current session.")
                        try:
                            self.page.goto(f"{self.url}/home", wait_until="networkidle")
                            self.page.goto(f"{self.url}/my_lessons", wait_until="networkidle")
                        except Exception as recovery_error:
                            logger.warning("Lesson-list recovery failed: %s", recovery_error)
                        continue
                    completed = self.lesson(lesson_type)
                    if not completed:
                        fail += 1
                        logger.error("iter %d incomplete; not counting it as successful.", i)
                        try:
                            self.page.goto(f"{self.url}/home", wait_until="networkidle")
                            self.page.goto(f"{self.url}/my_lessons", wait_until="networkidle")
                        except Exception:
                            self._new_ctx()
                        continue
                    self.page.goto(f"{self.url}/my_lessons", wait_until="networkidle"); self.s(2)
                    ok += 1
                    logger.info(f"iter {i} OK | {ok} ok, {fail} fail")
                except KeyboardInterrupt:
                    logger.info("Interrupted."); break
                except AIResponseError as e:
                    logger.error("Stopping run: %s", e)
                    raise
                except Exception as e:
                    fail += 1; logger.error(f"iter {i} FAIL: {e}")
                    try: self.page.reload(wait_until="networkidle")
                    except Exception: pass
                    if self.browser and self.browser.is_connected():
                        self._new_ctx()
            logger.info(f"\nDONE | ok={ok} fail={fail}")
        finally:
            self.close()


if __name__ == "__main__":
    Bot().run()
