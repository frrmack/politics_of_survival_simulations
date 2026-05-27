"""
Politics of Survival — Pygame GUI
Run from repo root:  python gui/main.py
"""

import sys
import os
import random

# Make sure the parent directory (repo root) is on the path
_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

import pygame

from config import GameConfig
from card import (Card, Engineers, Colonists, Military, Overtime, Genius, Propaganda)
from module import Module
from game import Game, PlayerView, RoundRecord
from strategy import (Strategy, CooperativeStrategy, AggressiveStrategy,
                      BalancedStrategy, RandomStrategy)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

W, H = 1280, 800
FPS  = 60

# Colors
BG           = (20, 25, 35)
PANEL        = (30, 36, 50)
PANEL2       = (40, 48, 65)
WHITE        = (255, 255, 255)
GREY         = (160, 160, 160)
DARK_GREY    = (80, 80, 90)
YELLOW       = (255, 230, 60)
GOLD         = (220, 170, 30)
RED          = (220, 60, 60)
GREEN        = (60, 200, 100)
BLUE         = (80, 140, 220)
TEXT_DARK    = (200, 210, 230)
P1_COLOR     = (70,  165, 155)   # muted teal  — P1 identity color
P2_COLOR     = (180,  75, 155)   # muted magenta — P2 identity color

CARD_COLORS = {
    Engineers:  (34,  120,  60),
    Colonists:  (60,  100, 180),
    Military:   (180,  40,  40),
    Overtime:   (20,  160,  90),
    Genius:     (180, 150,  20),
    Propaganda: (140,  50, 180),
}

CARD_ABBR = {
    Engineers:  "ENG",
    Colonists:  "COL",
    Military:   "MIL",
    Overtime:   "OVT",
    Genius:     "GEN",
    Propaganda: "PRO",
}

CARD_EFFECT = {
    Engineers:  ("+1 dev", ""),
    Colonists:  ("+1 inf", ""),
    Military:   ("+2 inf", "(-1 dev vs MIL)"),
    Overtime:   ("+2 dev", ""),
    Genius:     ("+1 inf", "+1 dev"),
    Propaganda: ("+2 inf", ""),
}

CARD_W, CARD_H = 90, 130
DIE_BOX = 100   # size of die box including border

# States
SETUP        = "SETUP"
ROUND_START  = "ROUND_START"
DEPLOY       = "DEPLOY"
PASS_SCREEN  = "PASS_SCREEN"
CONSEQUENCES = "CONSEQUENCES"
GAME_OVER    = "GAME_OVER"

PLAYER_NAMES = ["Player 1", "Player 2"]
STRATEGY_LABELS = ["Human", "Cooperative", "Aggressive", "Balanced", "Random"]

# ---------------------------------------------------------------------------
# HumanStrategy
# ---------------------------------------------------------------------------

class HumanStrategy(Strategy):
    def __init__(self):
        self._deployment = {}

    def set_deployment(self, d):
        self._deployment = d

    def choose_deployment(self, view: PlayerView) -> dict:
        d = self._deployment
        self._deployment = {}
        return d

# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def make_font(size, bold=False):
    return pygame.font.SysFont("segoeui", size, bold=bold)


def draw_text(surf, text, font, color, cx, cy, anchor="center"):
    img = font.render(text, True, color)
    r = img.get_rect()
    if anchor == "center":
        r.center = (cx, cy)
    elif anchor == "topleft":
        r.topleft = (cx, cy)
    elif anchor == "midleft":
        r.midleft = (cx, cy)
    elif anchor == "midright":
        r.midright = (cx, cy)
    surf.blit(img, r)
    return r


def draw_button(surf, text, font, rect, color, text_color=WHITE,
                border_color=None, border_w=2, disabled=False):
    bc = DARK_GREY if disabled else (border_color or GOLD)
    tc = DARK_GREY if disabled else text_color
    bg = (50, 55, 65) if disabled else color
    pygame.draw.rect(surf, bg, rect, border_radius=6)
    pygame.draw.rect(surf, bc, rect, border_w, border_radius=6)
    draw_text(surf, text, font, tc, rect.centerx, rect.centery)


def point_in_rect(pos, rect):
    return rect.collidepoint(pos)


def draw_multicolor_text(surf, parts, font, cy, anchor_cx):
    """Render [(text, color), ...] as a single line centered at anchor_cx, cy."""
    imgs = [font.render(text, True, color) for text, color in parts]
    total_w = sum(img.get_width() for img in imgs)
    x = anchor_cx - total_w // 2
    for img in imgs:
        surf.blit(img, (x, cy - img.get_height() // 2))
        x += img.get_width()


def _lead_str(p1_inf, p2_inf):
    """Return (text, color) describing the influence lead between two players."""
    diff = p1_inf - p2_inf
    if diff > 0:
        return f"P1 +{diff}", P1_COLOR
    elif diff < 0:
        return f"P2 +{-diff}", P2_COLOR
    else:
        return "0", WHITE


def draw_die(surf, cx, cy, level, ready, size=80):
    """Draw a die face with pips. level 1-6."""
    half = size // 2
    rx = cx - half
    ry = cy - half
    border_color = GOLD if ready else (100, 110, 130)
    border_w     = 4    if ready else 2
    die_bg       = (240, 235, 220) if ready else (190, 190, 200)
    pygame.draw.rect(surf, die_bg,      (rx, ry, size, size), border_radius=10)
    pygame.draw.rect(surf, border_color,(rx, ry, size, size), border_w, border_radius=10)

    pip_color = (30, 30, 40)
    pip_r = max(5, size // 14)
    # Pip layout per face (positions as fractions of die size, origin at top-left)
    pip_layouts = {
        1: [(0.5, 0.5)],
        2: [(0.25, 0.25), (0.75, 0.75)],
        3: [(0.25, 0.25), (0.5,  0.5),  (0.75, 0.75)],
        4: [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)],
        5: [(0.25, 0.25), (0.75, 0.25), (0.5,  0.5),  (0.25, 0.75), (0.75, 0.75)],
        6: [(0.25, 0.2), (0.75, 0.2),
            (0.25, 0.5), (0.75, 0.5),
            (0.25, 0.8), (0.75, 0.8)],
    }
    lvl = max(1, min(6, level))
    for (fx, fy) in pip_layouts.get(lvl, []):
        px = rx + int(fx * size)
        py = ry + int(fy * size)
        pygame.draw.circle(surf, pip_color, (px, py), pip_r)


def snapshot_modules(modules):
    """Return a list of (dev_level, influence[0], influence[1]) tuples."""
    return [(m.dev_level, m.influence[0], m.influence[1]) for m in modules]


def describe_effects(mod_idx, before, after, record):
    """Return a human-readable string of consequences for one module."""
    b_dev, b_p1, b_p2 = before[mod_idx]
    a_dev, a_p1, a_p2 = after[mod_idx]
    parts = []
    if a_p1 != b_p1:
        parts.append(f"P1 inf {'+' if a_p1>b_p1 else ''}{a_p1 - b_p1}")
    if a_p2 != b_p2:
        parts.append(f"P2 inf {'+' if a_p2>b_p2 else ''}{a_p2 - b_p2}")
    if a_dev != b_dev:
        parts.append(f"dev {'+' if a_dev>b_dev else ''}{a_dev - b_dev}")
    if not parts:
        parts.append("no change")
    # Check for MvM
    c1, c2 = record.deployments.get(mod_idx, (None, None))
    extra = "  [MvM!]" if isinstance(c1, Military) and isinstance(c2, Military) else ""
    return ", ".join(parts) + extra


# ---------------------------------------------------------------------------
# Mini card (used in consequences view, above/below modules)
# ---------------------------------------------------------------------------

MINI_W, MINI_H = 80, 62
MINI_GAP = 6

def draw_mini_card(surf, card, cx, cy):
    """Draw a compact card centered at (cx, cy)."""
    color = CARD_COLORS.get(type(card), DARK_GREY)
    rect = pygame.Rect(cx - MINI_W // 2, cy - MINI_H // 2, MINI_W, MINI_H)
    pygame.draw.rect(surf, color, rect, border_radius=6)
    pygame.draw.rect(surf, WHITE, rect, 1, border_radius=6)
    f_name = make_font(12, bold=True)
    f_eff  = make_font(10)
    draw_text(surf, type(card).__name__, f_name, WHITE, cx, cy - 14)
    lines = CARD_EFFECT.get(type(card), ("", ""))
    if lines[1]:
        draw_text(surf, lines[0], f_eff, TEXT_DARK, cx, cy + 1)
        draw_text(surf, lines[1], f_eff, TEXT_DARK, cx, cy + 13)
    else:
        draw_text(surf, lines[0], f_eff, TEXT_DARK, cx, cy + 7)
    return rect


# ---------------------------------------------------------------------------
# Card rendering
# ---------------------------------------------------------------------------

def draw_card(surf, card, x, y, selected=False, assigned=False,
              show_number=None, small=False):
    w = CARD_W if not small else 70
    h = CARD_H if not small else 100
    color = CARD_COLORS.get(type(card), DARK_GREY)
    if assigned:
        color = tuple(max(0, c - 80) for c in color)
    rect = pygame.Rect(x, y, w, h)
    pygame.draw.rect(surf, color, rect, border_radius=8)
    if selected:
        pygame.draw.rect(surf, YELLOW, rect, 3, border_radius=8)
    elif assigned:
        pygame.draw.rect(surf, DARK_GREY, rect, 2, border_radius=8)
    else:
        pygame.draw.rect(surf, WHITE, rect, 1, border_radius=8)

    f_big   = make_font(16 if not small else 13, bold=True)
    f_small = make_font(11 if not small else 10)

    name = type(card).__name__
    draw_text(surf, name, f_big, WHITE, x + w//2, y + h//4)
    lines = CARD_EFFECT.get(type(card), ("", ""))
    draw_text(surf, lines[0], f_small, TEXT_DARK, x + w//2, y + h*2//3)
    if lines[1]:
        draw_text(surf, lines[1], f_small, TEXT_DARK, x + w//2, y + h*2//3 + 14)

    if assigned and show_number is not None:
        badge_r = pygame.Rect(x + w - 22, y + 4, 18, 18)
        pygame.draw.ellipse(surf, YELLOW, badge_r)
        bf = make_font(12, bold=True)
        draw_text(surf, f"M{show_number+1}", bf, (20, 20, 20),
                  badge_r.centerx, badge_r.centery)
    return rect


# ---------------------------------------------------------------------------
# Slider widget
# ---------------------------------------------------------------------------

class Slider:
    def __init__(self, x, y, w, min_val, max_val, val, label):
        self.rect  = pygame.Rect(x, y, w, 20)
        self.min_v = min_val
        self.max_v = max_val
        self.val   = val
        self.label = label
        self._dragging = False

    def draw(self, surf):
        f = make_font(14)
        draw_text(surf, f"{self.label}: {self.val}", f, WHITE,
                  self.rect.x, self.rect.y - 18, anchor="topleft")
        pygame.draw.rect(surf, PANEL2, self.rect, border_radius=4)
        pygame.draw.rect(surf, GREY,   self.rect, 1,  border_radius=4)
        frac = (self.val - self.min_v) / max(1, self.max_v - self.min_v)
        kx = int(self.rect.x + frac * self.rect.w)
        ky = self.rect.centery
        pygame.draw.circle(surf, GOLD, (kx, ky), 10)

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.inflate(20, 20).collidepoint(event.pos):
                self._dragging = True
                self._update(event.pos[0])
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging = False
        elif event.type == pygame.MOUSEMOTION and self._dragging:
            self._update(event.pos[0])

    def _update(self, mx):
        frac = (mx - self.rect.x) / max(1, self.rect.w)
        frac = max(0.0, min(1.0, frac))
        self.val = int(round(self.min_v + frac * (self.max_v - self.min_v)))


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

class App:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("Politics of Survival")
        self.clock = pygame.time.Clock()

        # fonts
        self.f_title  = make_font(36, bold=True)
        self.f_h2     = make_font(22, bold=True)
        self.f_h3     = make_font(16, bold=True)
        self.f_body   = make_font(14)
        self.f_small  = make_font(12)

        self.state = SETUP
        self._init_setup()

    # ------------------------------------------------------------------
    # SETUP state
    # ------------------------------------------------------------------

    def _init_setup(self):
        self.p_type   = [0, 3]   # 0=Human, 1=Coop, 2=Agg, 3=Balanced, 4=Random
        self.sl_rounds  = Slider(200, 280, 300, 3, 8, 5, "Rounds")
        self.sl_modules = Slider(200, 360, 300, 4, 7, 5, "Modules")
        self.sl_launch  = Slider(200, 440, 300, 2, 6, 4, "Modules needed to launch")

    def _draw_setup(self):
        s = self.screen
        s.fill(BG)
        draw_text(s, "Politics of Survival", self.f_title, WHITE, W//2, 60)
        draw_text(s, "Game Setup", self.f_h2, GREY, W//2, 105)

        # Player type selectors
        for pi in range(2):
            lx = 180 + pi * 480
            p_color = P1_COLOR if pi == 0 else P2_COLOR
            draw_text(s, f"Player {pi+1}", self.f_h3, p_color, lx, 155, anchor="topleft")
            for si, label in enumerate(STRATEGY_LABELS):
                bx = lx + si * 88
                by = 188
                rect = pygame.Rect(bx, by, 82, 30)
                selected = self.p_type[pi] == si
                col = p_color if selected else PANEL2
                pygame.draw.rect(s, col, rect, border_radius=5)
                pygame.draw.rect(s, GREY, rect, 1, border_radius=5)
                tc  = (20, 20, 20) if selected else WHITE
                draw_text(s, label, self.f_small, tc, rect.centerx, rect.centery)

        # Sliders
        self.sl_rounds.draw(s)
        self.sl_modules.draw(s)
        self.sl_launch.draw(s)

        # Clamp launch needed
        self.sl_launch.max_v = self.sl_modules.val
        if self.sl_launch.val > self.sl_modules.val:
            self.sl_launch.val = self.sl_modules.val

        # Start button
        btn = pygame.Rect(W//2 - 120, 530, 240, 52)
        draw_button(s, "Start Game", self.f_h2, btn, (40, 120, 60), border_color=GREEN)
        self._start_btn = btn

        # Info blurb
        lines = [
            "Engineers: +0 inf, +1 dev   |   Colonists: +1 inf   |   Military: +2 inf",
            "Goal: control the most modules. Both lose if < modules_needed are READY.",
        ]
        for i, ln in enumerate(lines):
            draw_text(s, ln, self.f_small, DARK_GREY, W//2, 620 + i * 20)

    def _handle_setup(self, event):
        for pi in range(2):
            lx = 180 + pi * 480
            for si in range(len(STRATEGY_LABELS)):
                bx = lx + si * 88
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if pygame.Rect(bx, 188, 82, 30).collidepoint(event.pos):
                        self.p_type[pi] = si
        self.sl_rounds.handle_event(event)
        self.sl_modules.handle_event(event)
        self.sl_launch.handle_event(event)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._start_btn.collidepoint(event.pos):
                self._start_game()

    def _start_game(self):
        config = GameConfig(
            num_rounds=self.sl_rounds.val,
            num_modules=self.sl_modules.val,
            modules_needed_to_launch=self.sl_launch.val,
        )
        self.config = config
        strategies = []
        self.human_strategies = []
        for pi in range(2):
            t = self.p_type[pi]
            if t == 0:
                hs = HumanStrategy()
                self.human_strategies.append((pi, hs))
                strategies.append(hs)
            elif t == 1:
                strategies.append(CooperativeStrategy())
            elif t == 2:
                strategies.append(AggressiveStrategy())
            elif t == 3:
                strategies.append(BalancedStrategy())
            else:
                strategies.append(RandomStrategy())

        self.game = Game(config, strategies, rng=random.Random())
        self.human_players = {pi for pi, _ in self.human_strategies}
        self.both_human    = (0 in self.human_players and 1 in self.human_players)

        self.state          = ROUND_START
        self.current_deploy_player = None
        self.deploy_phase   = 0   # 0 = P1, 1 = P2
        self.selected_card_idx = None   # index into current player's hand
        self.assignments    = {}  # mod_idx -> hand_idx
        self.modules_before = None
        self.consequences_data = None

    # ------------------------------------------------------------------
    # ROUND_START state
    # ------------------------------------------------------------------

    def _draw_round_start(self):
        s = self.screen
        g = self.game
        draw_text(s, f"Round {g.round_num + 1} of {g.config.num_rounds}",
                  self.f_title, WHITE, W//2, 50)
        draw_text(s, "Ship Status", self.f_h2, GOLD, W//2, 95)
        self._draw_modules(s, top=257, interactive=False)
        btn = pygame.Rect(W//2 - 130, 680, 260, 52)
        draw_button(s, "Begin Deployment", self.f_h2, btn, (40, 80, 150), border_color=BLUE)
        self._begin_btn = btn
        # show hand info
        for pi in range(2):
            label = f"P{pi+1} hand: {len(g.hands[pi])} cards"
            draw_text(s, label, self.f_body, GREY, 80 + pi*1100, H - 30)

    def _handle_round_start(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._begin_btn.collidepoint(event.pos):
                self._start_deployment()

    def _start_deployment(self):
        # snapshot state before anything is played
        self.modules_before = snapshot_modules(self.game.modules)
        self.deploy_phase   = 0
        self.selected_card_idx = None
        self.assignments    = {}
        self._advance_deploy()

    def _advance_deploy(self):
        """Move to the next deployment sub-phase or trigger _play_round."""
        g = self.game
        # deploy_phase 0 = first deployer, 1 = second deployer
        ordered = [0, 1]  # always P1 then P2 for hot-seat

        while self.deploy_phase < 2:
            pi = ordered[self.deploy_phase]
            if pi in self.human_players:
                # Human needs to deploy
                self.current_deploy_player = pi
                self.selected_card_idx = None
                self.assignments   = {}
                self.state = DEPLOY
                return
            else:
                # AI player — will be handled in _play_round; just skip
                self.deploy_phase += 1

        # Both phases done (or both AI) — run the round
        self._run_round()

    def _run_round(self):
        """Actually run the round (may or may not involve human deployments)."""
        g = self.game
        g.round_num += 1

        # For human players: their HumanStrategy already has deployment set.
        # For AI players: _play_round will call choose_deployment.
        g._play_round()

        after = snapshot_modules(g.modules)
        record = g.history[-1]
        self.consequences_data = (self.modules_before, after, record)
        self.state = CONSEQUENCES

    # ------------------------------------------------------------------
    # DEPLOY state
    # ------------------------------------------------------------------

    def _draw_deploy(self):
        s = self.screen
        s.fill(BG)
        pi = self.current_deploy_player
        g  = self.game
        assert pi is not None
        p_color = P1_COLOR if pi == 0 else P2_COLOR
        draw_multicolor_text(s,
            [(f"Round {g.round_num + 1} — ", WHITE), (f"Player {pi+1} Deployment", p_color)],
            self.f_title, 38, W//2)
        draw_text(s, "Click a card to select, then click a module slot to assign it.",
                  self.f_body, GREY, W//2, 72)

        # Module slots row
        self._draw_modules(s, top=190, interactive=True,
                           show_assignments=True, deploy_player=pi)

        # Hand
        hand = g.hands[pi]
        assigned_hand_idxs = set(self.assignments.values())

        hand_y = 450
        draw_text(s, "Your Hand:", self.f_h3, p_color, 40, hand_y - 28, anchor="topleft")

        # Lay out cards in up to 2 rows
        cards_per_row = min(len(hand), 8)
        row_w = cards_per_row * (CARD_W + 10)
        start_x = (W - row_w) // 2
        self._card_rects = {}
        for ci, card in enumerate(hand):
            row   = ci // 8
            col   = ci %  8
            cx    = start_x + col * (CARD_W + 10)
            cy    = hand_y + row * (CARD_H + 10)
            is_sel  = (ci == self.selected_card_idx)
            is_ass  = (ci in assigned_hand_idxs)
            # Find which module this hand slot is assigned to
            mod_num = None
            for mi, hi in self.assignments.items():
                if hi == ci:
                    mod_num = mi
            r = draw_card(s, card, cx, cy,
                          selected=is_sel,
                          assigned=is_ass,
                          show_number=mod_num)
            self._card_rects[ci] = (r, card)

        # Confirm button
        all_assigned = len(self.assignments) == g.config.num_modules
        btn = pygame.Rect(W//2 - 110, H - 120, 220, 48)
        draw_button(s, "Confirm Deployment", self.f_h2, btn,
                    (40, 120, 60), border_color=GREEN, disabled=not all_assigned)
        self._confirm_btn = btn

        # Count assigned
        draw_text(s, f"{len(self.assignments)}/{g.config.num_modules} modules assigned",
                  self.f_body, GREY, W//2, H - 62)

    def _handle_deploy(self, event):
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        pos = event.pos
        g   = self.game
        pi  = self.current_deploy_player

        # Guard: draw must have run at least once to populate these dicts
        if not hasattr(self, '_card_rects') or not hasattr(self, '_module_slots'):
            return

        # Check card clicks
        for ci, (r, _) in self._card_rects.items():
            if r.collidepoint(pos):
                if ci in self.assignments.values():
                    # Clicking assigned card: unassign it
                    for mi, hi in list(self.assignments.items()):
                        if hi == ci:
                            del self.assignments[mi]
                            break
                    self.selected_card_idx = None
                elif ci == self.selected_card_idx:
                    # Deselect
                    self.selected_card_idx = None
                else:
                    self.selected_card_idx = ci
                return

        # Check module slot clicks (only in interactive area)
        for mi, mr in self._module_slots.items():
            if mr.collidepoint(pos):
                if self.selected_card_idx is not None:
                    # Assign selected hand slot to this module
                    self.assignments[mi] = self.selected_card_idx
                    self.selected_card_idx = None
                elif mi in self.assignments:
                    # Click module with no card selected: unassign
                    del self.assignments[mi]
                return

        # Confirm button
        if len(self.assignments) == g.config.num_modules:
            if self._confirm_btn.collidepoint(pos):
                self._confirm_deployment()

    def _confirm_deployment(self):
        g  = self.game
        pi = self.current_deploy_player
        assert pi is not None
        hand = g.hands[pi]
        deployment = {mod_idx: hand[hi] for mod_idx, hi in self.assignments.items() if hi is not None}
        for p, hs in self.human_strategies:
            if p == pi:
                hs.set_deployment(deployment)
                break

        self.deploy_phase += 1

        # If we have 2 humans and just finished P1, show pass screen
        if self.both_human and self.deploy_phase == 1:
            self.state = PASS_SCREEN
        else:
            self._advance_deploy()

    # ------------------------------------------------------------------
    # PASS_SCREEN state
    # ------------------------------------------------------------------

    def _draw_pass_screen(self):
        s = self.screen
        s.fill((10, 10, 15))
        draw_text(s, "Pass the device to Player 2", self.f_title, WHITE, W//2, H//2 - 60)
        draw_text(s, "Don't look!", self.f_h2, RED, W//2, H//2)
        btn = pygame.Rect(W//2 - 100, H//2 + 60, 200, 50)
        draw_button(s, "Ready", self.f_h2, btn, (40, 80, 40), border_color=GREEN)
        self._pass_ready_btn = btn

    def _handle_pass_screen(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._pass_ready_btn.collidepoint(event.pos):
                self.state = DEPLOY
                self.current_deploy_player = 1
                self.selected_card_idx = None
                self.assignments   = {}

    # ------------------------------------------------------------------
    # CONSEQUENCES state
    # ------------------------------------------------------------------

    def _draw_consequences(self):
        s = self.screen
        s.fill(BG)
        g = self.game
        assert self.consequences_data is not None
        before, _, record = self.consequences_data

        draw_text(s, f"Round {g.round_num} Consequences", self.f_title, WHITE, W//2, 38)

        self._draw_modules(s, top=188, interactive=False,
                           played_cards=record.deployments, before_state=before)

        # Button
        last_round = g.round_num >= g.config.num_rounds or g.game_over
        btn_label  = "See Final Result" if last_round else "Next Round"
        btn = pygame.Rect(W//2 - 120, H - 65, 240, 48)
        draw_button(s, btn_label, self.f_h2, btn, (40, 80, 150), border_color=BLUE)
        self._next_btn = btn

    def _handle_consequences(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._next_btn.collidepoint(event.pos):
                g = self.game
                if g.round_num >= g.config.num_rounds or g.game_over:
                    self.state = GAME_OVER
                else:
                    self.state = ROUND_START
                    self.deploy_phase   = 0
                    self.selected_card_idx = None
                    self.assignments    = {}

    # ------------------------------------------------------------------
    # GAME_OVER state
    # ------------------------------------------------------------------

    def _draw_game_over(self):
        s = self.screen
        g = self.game
        result = g._build_result()

        draw_text(s, "Game Over", self.f_title, WHITE, W//2, 45)

        if result.extinction:
            msg = f"EXTINCTION — only {result.ready_modules}/{g.config.modules_needed_to_launch} modules ready!"
            draw_text(s, msg, self.f_h2, RED, W//2, 90)
        else:
            if result.winner is None:
                msg = "IT'S A DRAW!"
                col = YELLOW
            else:
                msg = f"Player {result.winner + 1} Wins!"
                col = P1_COLOR if result.winner == 0 else P2_COLOR
            draw_text(s, msg, self.f_h2, col, W//2, 90)
            draw_text(s,
                      f"Modules controlled: P1={result.modules_won[0]}  P2={result.modules_won[1]}",
                      self.f_body, WHITE, W//2, 125)

        draw_text(s, f"Rounds played: {result.rounds_played}   Ready modules: {result.ready_modules}",
                  self.f_body, GREY, W//2, 155)

        self._draw_modules(s, top=256, interactive=False)

        btn = pygame.Rect(W//2 - 130, H - 75, 260, 52)
        draw_button(s, "Play Again", self.f_h2, btn, (40, 80, 40), border_color=GREEN)
        self._again_btn = btn

    def _handle_game_over(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._again_btn.collidepoint(event.pos):
                self.state = SETUP
                self._init_setup()

    # ------------------------------------------------------------------
    # Shared module drawing
    # ------------------------------------------------------------------

    def _draw_modules(self, surf, top=130, interactive=False,
                      show_assignments=False, deploy_player=None,
                      small_die=False, played_cards=None,
                      before_state=None):
        g = self.game
        n = g.config.num_modules
        die_sz   = 60 if small_die else 80
        box_w    = die_sz + 30
        slot_h   = die_sz + (90 if not small_die else 65)
        spacing  = max(box_w + 10, (W - 80) // n)
        total_w  = spacing * n
        start_x  = (W - total_w) // 2

        # When showing played cards, shift the module box down to make room for P2 card above
        card_band = (MINI_H + MINI_GAP) if played_cards else 0
        box_top  = top + card_band

        if interactive:
            self._module_slots = {}

        for mi, mod in enumerate(g.modules):
            cx = start_x + mi * spacing + spacing // 2

            # Background box
            box_rect = pygame.Rect(cx - box_w//2, box_top, box_w, slot_h)
            assigned_here = (show_assignments and mi in self.assignments)
            box_bg = (50, 60, 80) if assigned_here else PANEL
            lead = mod.winner()  # 0, 1, or None
            lead_color = P1_COLOR if lead == 0 else (P2_COLOR if lead == 1 else DARK_GREY)
            pygame.draw.rect(surf, box_bg, box_rect, border_radius=8)
            pygame.draw.rect(surf, lead_color, box_rect, 2, border_radius=8)

            if interactive:
                self._module_slots[mi] = box_rect

            # Module label
            draw_text(surf, f"M{mi+1}", self.f_h3, GOLD, cx, box_top + 14)

            # Die
            die_y = box_top + 30
            draw_die(surf, cx, die_y + die_sz//2, mod.dev_level, mod.is_ready, size=die_sz)

            # Status
            status_y = die_y + die_sz + 8
            if mod.is_ready:
                draw_text(surf, "READY", self.f_small, GREEN, cx, status_y)
            else:
                draw_text(surf, f"needs +{mod.READY_THRESHOLD - mod.dev_level}",
                          self.f_small, RED, cx, status_y)

            # Influence lead
            inf_y = status_y + 16
            if before_state is not None:
                # Consequences view: show old → new
                _, b_p1, b_p2 = before_state[mi]
                old_txt, old_col = _lead_str(b_p1, b_p2)
                new_txt, new_col = _lead_str(mod.influence[0], mod.influence[1])
                draw_multicolor_text(surf,
                    [(old_txt, old_col), (" → ", GREY), (new_txt, new_col)],
                    self.f_small, inf_y, cx)
            else:
                diff = mod.influence[0] - mod.influence[1]
                if diff > 0:
                    draw_text(surf, f"P1 +{diff}", self.f_small, P1_COLOR, cx, inf_y)
                elif diff < 0:
                    draw_text(surf, f"P2 +{-diff}", self.f_small, P2_COLOR, cx, inf_y)

            # Assignment indicator
            if show_assignments and mi in self.assignments:
                hi = self.assignments[mi]
                if hi is not None and self.current_deploy_player is not None:
                    acard = g.hands[self.current_deploy_player][hi]
                    abbr  = CARD_ABBR.get(type(acard), "???")
                    abbr_y = inf_y + 16
                    col   = CARD_COLORS.get(type(acard), GREY)
                    draw_text(surf, abbr, self.f_small, col, cx, abbr_y)

            # Played cards (consequences view): P2 above, P1 below
            if played_cards and mi in played_cards:
                c1, c2 = played_cards[mi]
                if c2:
                    draw_mini_card(surf, c2, cx, top + MINI_H // 2)
                if c1:
                    draw_mini_card(surf, c1, cx, box_top + slot_h + MINI_GAP + MINI_H // 2)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):
        running = True
        while running:
            self.clock.tick(FPS)
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    running = False
                    break
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    running = False
                    break

                if self.state == SETUP:
                    self._handle_setup(event)
                elif self.state == ROUND_START:
                    self._handle_round_start(event)
                elif self.state == DEPLOY:
                    self._handle_deploy(event)
                elif self.state == PASS_SCREEN:
                    self._handle_pass_screen(event)
                elif self.state == CONSEQUENCES:
                    self._handle_consequences(event)
                elif self.state == GAME_OVER:
                    self._handle_game_over(event)

            # Auto-play for AI vs AI
            if hasattr(self, 'game') and self.state == ROUND_START and not self.human_players:
                self._start_deployment()

            # Draw
            self.screen.fill(BG)
            if self.state == SETUP:
                self._draw_setup()
            elif self.state == ROUND_START:
                self._draw_round_start()
            elif self.state == DEPLOY:
                self._draw_deploy()
            elif self.state == PASS_SCREEN:
                self._draw_pass_screen()
            elif self.state == CONSEQUENCES:
                self._draw_consequences()
            elif self.state == GAME_OVER:
                self._draw_game_over()

            pygame.display.flip()

        pygame.quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    App().run()
