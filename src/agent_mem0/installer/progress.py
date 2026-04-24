"""Installation progress bar with rich.

Provides a non-scrolling progress bar for the install wizard.
The bar stays fixed at the terminal bottom while original subprocess
output scrolls above it.
"""

from __future__ import annotations

import re
import subprocess
import threading
from dataclasses import dataclass

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)


@dataclass
class Step:
    """A single step in the installation plan."""

    key: str
    description: str
    weight: int = 10


class InstallProgress:
    """Non-scrolling progress bar for the install wizard.

    All subprocess output is printed above the progress bar in real time.
    The progress bar stays fixed at the terminal bottom.

    Usage::

        tracker = InstallProgress()
        tracker.plan([
            Step("install_ollama", "安装 Ollama", weight=15),
            Step("pull_model", "拉取模型 qwen2.5:7b", weight=25),
        ])
        with tracker:
            tracker.begin_step("install_ollama")
            # ... do work ...
            tracker.complete_step("install_ollama")
    """

    def __init__(self, console: Console | None = None):
        self.console = console or Console()
        self._steps: list[Step] = []
        self._step_map: dict[str, Step] = {}
        self._progress: Progress | None = None
        self._task_id = None
        self._total_weight = 0
        self._current_step_idx = 0

    def plan(self, steps: list[Step]) -> None:
        """Set the execution plan."""
        self._steps = steps
        self._step_map = {s.key: s for s in steps}
        self._total_weight = sum(s.weight for s in steps)

    def __enter__(self):
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.fields[step_info]}", style="dim"),
            TextColumn("{task.description}", style="bold blue"),
            BarColumn(
                bar_width=30,
                complete_style="green",
                finished_style="bold green",
            ),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=self.console,
        )
        self._progress.start()
        self._task_id = self._progress.add_task(
            "准备中...",
            total=self._total_weight,
            step_info=f"[0/{len(self._steps)}]",
        )
        self._current_step_idx = 0
        return self

    def __exit__(self, *args):
        if self._progress:
            n = len(self._steps)
            self._progress.update(
                self._task_id,
                description="安装完成",
                step_info=f"[{n}/{n}]",
                completed=self._total_weight,
            )
            self._progress.stop()

    def begin_step(self, key: str) -> None:
        """Mark a step as starting — updates description and step counter."""
        step = self._step_map[key]
        self._current_step_idx = self._steps.index(step) + 1
        if self._progress and self._task_id is not None:
            self._progress.update(
                self._task_id,
                description=step.description,
                step_info=f"[{self._current_step_idx}/{len(self._steps)}]",
            )

    def complete_step(self, key: str) -> None:
        """Mark a step as done — advances the progress bar."""
        step = self._step_map[key]
        if self._progress and self._task_id is not None:
            self._progress.advance(self._task_id, step.weight)

    def update_description(self, desc: str) -> None:
        """Update the current step description (e.g., to show sub-progress)."""
        if self._progress and self._task_id is not None:
            self._progress.update(self._task_id, description=desc)

    def print(self, msg: str) -> None:
        """Print a message above the progress bar (bar stays at bottom)."""
        if self._progress:
            self._progress.console.print(msg)
        else:
            self.console.print(msg)

    def run_subprocess(
        self,
        cmd: list[str],
        key: str,
        *,
        parse_pct: bool = False,
    ) -> tuple[bool, str]:
        """Run a subprocess for the given step.

        All subprocess output is printed above the progress bar in real time.

        If *parse_pct* is True, also parses percentage from output to update
        the progress description, and deduplicates ``\\r``-based progress
        lines (only prints layer changes and 100% completions).

        Returns ``(success, combined_output)``.
        """
        self.begin_step(key)
        success, output = self._run_streaming(cmd, key, parse_pct=parse_pct)
        self.complete_step(key)
        return success, output

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    # Regex to strip ANSI escape sequences (cursor control, colors, etc.)
    _ANSI_RE = re.compile(r"\x1b\[[\d;?]*[a-zA-Zhl]")

    @classmethod
    def _strip_ansi(cls, text: str) -> str:
        """Remove ANSI escape sequences from text."""
        return cls._ANSI_RE.sub("", text)

    def _run_streaming(
        self,
        cmd: list[str],
        key: str,
        *,
        parse_pct: bool = False,
    ) -> tuple[bool, str]:
        """Run a command, streaming its output above the progress bar.

        Merges stdout and stderr into a single stream. Reads byte-by-byte
        to handle both ``\\n``-terminated and ``\\r``-based output.

        All ANSI escape sequences are stripped before processing.

        When *parse_pct* is True:
          - Extracts percentage from output to update the progress description
          - Deduplicates transient progress lines (spinners, intermediate
            percentages): only prints when content meaningfully changes
            (new layer, 100% complete, or non-progress text)
        """
        step = self._step_map[key]
        base_desc = step.description

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        output_lines: list[str] = []
        last_printed_content = ""

        def _read_and_print():
            nonlocal last_printed_content
            buf = b""

            while True:
                chunk = proc.stdout.read(1)  # type: ignore[union-attr]
                if not chunk:
                    if buf:
                        line = buf.decode("utf-8", errors="replace")
                        last_printed_content = self._process_line(
                            line, parse_pct, base_desc,
                            output_lines, last_printed_content,
                        )
                    break

                if chunk in (b"\n", b"\r"):
                    line = buf.decode("utf-8", errors="replace")
                    buf = b""
                    last_printed_content = self._process_line(
                        line, parse_pct, base_desc,
                        output_lines, last_printed_content,
                    )
                else:
                    buf += chunk

        t = threading.Thread(target=_read_and_print, daemon=True)
        t.start()

        proc.wait()
        t.join(timeout=30)

        return proc.returncode == 0, "\n".join(output_lines)

    def _process_line(
        self,
        raw_line: str,
        parse_pct: bool,
        base_desc: str,
        output_lines: list[str],
        last_printed_content: str,
    ) -> str:
        """Process a single line of subprocess output.

        Strips ANSI codes, deduplicates transient lines when parse_pct
        is True, and prints meaningful lines above the progress bar.

        Returns the content string used for dedup comparison.
        """
        # Strip ANSI escape sequences
        clean = self._strip_ansi(raw_line).strip()
        if not clean:
            return last_printed_content

        output_lines.append(clean)

        if parse_pct:
            # Update progress bar description with percentage
            pct_match = re.search(r"(\d+)%", clean)
            if pct_match:
                pct = int(pct_match.group(1))
                self.update_description(f"{base_desc} ({pct}%)")

            # Decide whether to print this line or skip (dedup)
            if self._is_transient_line(clean):
                # Transient line (spinner, progress update)
                # Extract stable prefix for comparison
                # "pulling 8934d96d3f08... 45% ▕██..." → "pulling 8934d96d3f08"
                prefix = re.split(r"[\.\s]*\d+%", clean)[0].strip()
                # Also strip spinner characters
                prefix = re.sub(r"[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]", "", prefix).strip()
                if not prefix:
                    prefix = clean[:20]

                is_new_content = prefix != last_printed_content
                is_complete = pct_match and int(pct_match.group(1)) == 100

                if is_new_content or is_complete:
                    self.print(f"[dim]  {clean}[/dim]")
                    return prefix
                return last_printed_content
            else:
                # Non-transient line (status messages like "verifying sha256",
                # "writing manifest", "success", error messages, etc.)
                self.print(f"[dim]  {clean}[/dim]")
                return clean

        # Non-parse_pct mode: always print every line
        self.print(f"[dim]  {clean}[/dim]")
        return last_printed_content

    @staticmethod
    def _is_transient_line(line: str) -> bool:
        """Check if a line is a transient progress/spinner line.

        These are lines that get overwritten in a real terminal
        (spinners, download bars, percentage updates).
        """
        # Contains spinner characters
        if re.search(r"[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]", line):
            return True
        # Contains a progress bar (block characters)
        if "▕" in line or "█" in line or "▏" in line:
            return True
        # Contains percentage with size info (e.g. "45% 2.1 GB/4.7 GB")
        if re.search(r"\d+%\s+▕", line):
            return True
        return False
