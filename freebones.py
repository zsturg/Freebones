"""
FreeBones — Standalone Paper Doll Editor
Hierarchy-based sprite rigging with auto-behaviors (blink, idle breathing),
user-defined keyframed macros, and PNG Sequence exporting.
"""

from __future__ import annotations
import os
import math
import random
import json
import uuid
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem, QFrame,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QSlider, QComboBox, QLineEdit, QDoubleSpinBox, QCheckBox, 
    QFileDialog, QInputDialog, QMessageBox, QScrollArea,
    QFormLayout, QDialog, QDialogButtonBox,
)
from PySide6.QtCore import Qt, Signal, QPointF, QTimer, QRectF
from PySide6.QtGui import (
    QColor, QPainter, QPixmap, QPen, QBrush, QTransform, QImage, QPolygonF
)

# ─────────────────────────────────────────────────────────────
#  DATA MODELS (Formerly from models.py)
# ─────────────────────────────────────────────────────────────

@dataclass
class RegisteredImage:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    path: Optional[str] = None
    category: str = "character"

    def to_dict(self):
        return {"id": self.id, "name": self.name, "path": self.path, "category": self.category}

    @classmethod
    def from_dict(cls, d):
        return cls(**d)

@dataclass
class MeshDeformConfig:
    enabled: bool = False
    grid_cols: int = 4
    grid_rows: int = 4

    def to_dict(self): return self.__dict__.copy()
    @classmethod
    def from_dict(cls, d): return cls(**{k: v for k, v in d.items() if k in ('enabled', 'grid_cols', 'grid_rows')})

    @property
    def vert_count(self):
        return (self.grid_cols + 1) * (self.grid_rows + 1)

@dataclass
class MeshKeyframe:
    """Stores all vertex offsets for a mesh-deformable layer at a point in time."""
    time: float = 0.0
    layer_id: str = ""
    offsets: list[list[float]] = field(default_factory=list)  # [[dx, dy], ...]

    def to_dict(self):
        return {"time": self.time, "layer_id": self.layer_id, "offsets": self.offsets}

    @classmethod
    def from_dict(cls, d):
        return cls(
            time=float(d.get("time", 0.0)),
            layer_id=d.get("layer_id", ""),
            offsets=d.get("offsets", []),
        )

@dataclass
class PaperDollLayer:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "New Layer"
    image_id: Optional[str] = None
    origin_x: float = 0.0
    origin_y: float = 0.0
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    children: list["PaperDollLayer"] = field(default_factory=list)
    mesh_deform: MeshDeformConfig = field(default_factory=MeshDeformConfig)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "image_id": self.image_id,
            "origin_x": self.origin_x, "origin_y": self.origin_y,
            "x": self.x, "y": self.y, "rotation": self.rotation,
            "scale_x": self.scale_x, "scale_y": self.scale_y,
            "children": [c.to_dict() for c in self.children],
            "mesh_deform": self.mesh_deform.to_dict(),
        }

    @classmethod
    def from_dict(cls, d):
        obj = cls()
        obj.id = d.get("id", obj.id)
        obj.name = d.get("name", "New Layer")
        obj.image_id = d.get("image_id")
        obj.origin_x = float(d.get("origin_x", 0.0))
        obj.origin_y = float(d.get("origin_y", 0.0))
        obj.x = float(d.get("x", 0.0))
        obj.y = float(d.get("y", 0.0))
        obj.rotation = float(d.get("rotation", 0.0))
        # Backwards compat: read old single "scale" into both axes
        old_scale = float(d.get("scale", 1.0))
        obj.scale_x = float(d.get("scale_x", old_scale))
        obj.scale_y = float(d.get("scale_y", old_scale))
        obj.children =[PaperDollLayer.from_dict(c) for c in d.get("children", [])]
        obj.mesh_deform = MeshDeformConfig.from_dict(d.get("mesh_deform", {}))
        return obj

@dataclass
class BlinkConfig:
    enabled: bool = False
    layer_id: str = ""
    alt_image_id: Optional[str] = None
    interval_min: float = 2.0
    interval_max: float = 5.0
    blink_duration: float = 0.15

    def to_dict(self): return self.__dict__.copy()
    @classmethod
    def from_dict(cls, d): return cls(**d)

@dataclass
class IdleBreathingConfig:
    enabled: bool = False
    layer_id: str = ""
    scale_amount: float = 0.02
    speed: float = 3.0
    affect_children: bool = True

    def to_dict(self): return self.__dict__.copy()
    @classmethod
    def from_dict(cls, d): return cls(**d)

@dataclass
class PaperDollKeyframe:
    time: float = 0.0
    layer_id: str = ""
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0

    def to_dict(self): return self.__dict__.copy()
    @classmethod
    def from_dict(cls, d):
        # Backwards compat: read old single "scale" into both axes
        old_scale = float(d.get("scale", 1.0))
        return cls(
            time=float(d.get("time", 0.0)),
            layer_id=d.get("layer_id", ""),
            x=float(d.get("x", 0.0)),
            y=float(d.get("y", 0.0)),
            rotation=float(d.get("rotation", 0.0)),
            scale_x=float(d.get("scale_x", old_scale)),
            scale_y=float(d.get("scale_y", old_scale)),
        )

@dataclass
class PaperDollMacro:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "New Macro"
    duration: float = 1.0
    loop: bool = False
    keyframes: list[PaperDollKeyframe] = field(default_factory=list)
    mesh_keyframes: list[MeshKeyframe] = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "duration": self.duration, "loop": self.loop,
            "keyframes":[k.to_dict() for k in self.keyframes],
            "mesh_keyframes": [mk.to_dict() for mk in self.mesh_keyframes],
        }

    @classmethod
    def from_dict(cls, d):
        obj = cls()
        obj.id = d.get("id", obj.id)
        obj.name = d.get("name", "New Macro")
        obj.duration = float(d.get("duration", 1.0))
        obj.loop = d.get("loop", False)
        obj.keyframes =[PaperDollKeyframe.from_dict(k) for k in d.get("keyframes", [])]
        obj.mesh_keyframes = [MeshKeyframe.from_dict(mk) for mk in d.get("mesh_keyframes", [])]
        return obj

@dataclass
class PaperDollAsset:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "New Paper Doll"
    root_layers: list[PaperDollLayer] = field(default_factory=list)
    blink: BlinkConfig = field(default_factory=BlinkConfig)
    idle_breathing: IdleBreathingConfig = field(default_factory=IdleBreathingConfig)
    macros: list[PaperDollMacro] = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name,
            "root_layers": [l.to_dict() for l in self.root_layers],
            "blink": self.blink.to_dict(),
            "idle_breathing": self.idle_breathing.to_dict(),
            "macros": [m.to_dict() for m in self.macros],
        }

    @classmethod
    def from_dict(cls, d):
        obj = cls()
        obj.id = d.get("id", obj.id)
        obj.name = d.get("name", "New Paper Doll")
        obj.root_layers =[PaperDollLayer.from_dict(l) for l in d.get("root_layers", [])]
        obj.blink = BlinkConfig.from_dict(d.get("blink", {}))
        obj.idle_breathing = IdleBreathingConfig.from_dict(d.get("idle_breathing", {}))
        obj.macros =[PaperDollMacro.from_dict(m) for m in d.get("macros", [])]
        return obj

    def find_layer(self, layer_id: str) -> Optional[PaperDollLayer]:
        def _search(layers):
            for l in layers:
                if l.id == layer_id:
                    return l
                found = _search(l.children)
                if found:
                    return found
            return None
        return _search(self.root_layers)

@dataclass
class Project:
    images: list[RegisteredImage] = field(default_factory=list)
    paper_dolls: list[PaperDollAsset] = field(default_factory=list)

    def get_image(self, image_id: str) -> Optional[RegisteredImage]:
        return next((i for i in self.images if i.id == image_id), None)

    def get_paper_doll(self, doll_id: str) -> Optional[PaperDollAsset]:
        return next((d for d in self.paper_dolls if d.id == doll_id), None)

    def to_dict(self):
        return {
            "images": [i.to_dict() for i in self.images],
            "paper_dolls": [pd.to_dict() for pd in self.paper_dolls]
        }

    @classmethod
    def from_dict(cls, d):
        p = cls()
        p.images = [RegisteredImage.from_dict(i) for i in d.get("images", [])]
        p.paper_dolls =[PaperDollAsset.from_dict(pd) for pd in d.get("paper_dolls", [])]
        return p

    @classmethod
    def new(cls) -> "Project":
        return cls()


# ─────────────────────────────────────────────────────────────
#  Aesthetic Constants
# ─────────────────────────────────────────────────────────────
DARK    = "#0f0f12"
PANEL   = "#16161c"
SURFACE = "#1e1e28"
SURF2   = "#26263a"
BORDER  = "#2e2e42"
ACCENT  = "#7c6aff"
TEXT    = "#e8e6f0"
DIM     = "#7a7890"

def _section(title: str):
    lbl = QLabel(title.upper())
    lbl.setStyleSheet(f"color: {DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; padding-top: 10px;")
    return lbl

def _btn(label: str, accent=False, icon_style=False):
    b = QPushButton(label)
    height = 24 if icon_style else 28
    b.setFixedHeight(height)
    bg = ACCENT if accent else SURF2
    b.setStyleSheet(f"""
        QPushButton {{
            background-color: {bg}; color: white;
            border: 1px solid {BORDER}; border-radius: 4px;
            font-size: 11px; font-weight: 600; padding: 0 8px;
        }}
        QPushButton:hover {{ background-color: {ACCENT}; }}
    """)
    return b

def _keyframe_diamond():
    b = QPushButton("◆")
    b.setFixedSize(20, 20)
    b.setCheckable(True)
    b.setStyleSheet(f"""
        QPushButton {{
            background: transparent; color: {DIM}; border: none; font-size: 14px;
            padding: 0; min-width: 0; max-width: 20px; max-height: 20px;
        }}
        QPushButton:checked {{ color: {ACCENT}; }}
        QPushButton:hover {{ color: white; }}
    """)
    return b

def _make_spin(value=0.0, minimum=-9999.0, maximum=9999.0, step=1.0, decimals=1):
    s = QDoubleSpinBox()
    s.setRange(minimum, maximum)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    s.setValue(value)
    s.setFixedHeight(24)
    s.setStyleSheet(f"background: {SURF2}; border: 1px solid {BORDER}; color: {TEXT}; padding: 2px 4px;")
    return s


class CollapsibleSection(QWidget):
    """A collapsible section with a toggle header and content area."""
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._toggle_btn = QPushButton(f"▶ {title.upper()}")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(False)
        self._toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {DIM}; border: none;
                font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
                text-align: left; padding: 6px 0;
            }}
            QPushButton:hover {{ color: {TEXT}; }}
        """)
        self._toggle_btn.toggled.connect(self._on_toggled)
        layout.addWidget(self._toggle_btn)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 4)
        self._content_layout.setSpacing(4)
        self._content.setVisible(False)
        layout.addWidget(self._content)
        self._title = title

    def _on_toggled(self, checked):
        self._content.setVisible(checked)
        arrow = "▼" if checked else "▶"
        self._toggle_btn.setText(f"{arrow} {self._title.upper()}")

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def set_expanded(self, expanded: bool):
        self._toggle_btn.setChecked(expanded)


# ── Canvas ─────────────────────────────────────────────────────

class PaperDollCanvas(QGraphicsView):
    """Preview canvas that renders the paper doll layer hierarchy."""
    layer_moved = Signal(str, float, float)
    origin_moved = Signal(str, float, float)
    layer_clicked = Signal(str)
    mesh_vert_moved = Signal(str, int, float, float)  # layer_id, vert_index, dx, dy
    mesh_cell_clicked = Signal(int, int)  # row, col of clicked cell (-1,-1 for deselect)

    ORIGIN_SIZE = 12
    MESH_HANDLE_RADIUS = 5

    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene(0, 0, 960, 544)
        self.setScene(self._scene)
        self.setBackgroundBrush(QColor(DARK))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setStyleSheet(f"border: none; background: {DARK};")
        self.setDragMode(QGraphicsView.DragMode.NoDrag)

        self._pixmap_items: dict[str, QGraphicsPixmapItem] = {}
        self._pixmap_cache: dict[str, QPixmap] = {}

        self._origin_scene_pos: dict[str, QPointF] = {}
        self._selected_layer_id: str | None = None
        self._dragging: str | None = None
        self._drag_layer_id: str | None = None
        self._drag_start_pos = QPointF()

        self._origin_circle = None
        self._origin_hline = None
        self._origin_vline = None

        self._image_swaps: dict[str, str] = {}
        self._scale_offsets: dict[str, tuple[float, float]] = {}

        # Mesh deform state
        self._mesh_vert_handles: list = []  # QGraphicsEllipseItem list for selected layer
        self._mesh_line_items: list = []    # QGraphicsLineItem list for grid lines
        self._mesh_offsets: dict[str, list[list[float]]] = {}  # layer_id -> [[dx,dy],...]
        self._dragging_vert_index: int | None = None
        self._exporting: bool = False  # When True, suppress all overlay rendering

    def set_selected_layer(self, layer_id: str | None):
        self._selected_layer_id = layer_id
        self._update_origin_marker()
        self._update_mesh_overlay()

    def set_mesh_offsets(self, layer_id: str, offsets: list[list[float]]):
        """Set current mesh vertex offsets for a layer (used during playback)."""
        self._mesh_offsets[layer_id] = offsets

    def clear_mesh_offsets(self):
        self._mesh_offsets.clear()

    def get_mesh_offsets(self, layer_id: str) -> list[list[float]]:
        return self._mesh_offsets.get(layer_id, [])

    def rebuild(self, asset: PaperDollAsset | None, project: Project | None,
                image_swaps: dict[str, str] | None = None, scale_offsets: dict[str, tuple[float, float]] | None = None):
        self._scene.clear()
        self._pixmap_items.clear()
        self._origin_scene_pos.clear()
        self._origin_circle = None
        self._origin_hline = None
        self._origin_vline = None
        self._mesh_vert_handles.clear()
        self._mesh_line_items.clear()
        if not asset or not project:
            self._current_asset_ref = None
            self._current_project_ref = None
            return
        self._current_asset_ref = asset
        self._current_project_ref = project
        self._image_swaps = image_swaps or {}
        self._scale_offsets = scale_offsets or {}
        self._draw_layers(asset.root_layers, project, QTransform())
        self._update_origin_marker()
        self._update_mesh_overlay()

    def update_transforms(self, asset: PaperDollAsset | None, project: Project | None,
                          image_swaps: dict[str, str] | None = None, scale_offsets: dict[str, tuple[float, float]] | None = None):
        """FAST UPDATE: Adjusts matrix transforms directly instead of destroying the scene."""
        if not asset or not project: return
        self._current_asset_ref = asset
        self._current_project_ref = project
        self._image_swaps = image_swaps or {}
        self._scale_offsets = scale_offsets or {}
        self._origin_scene_pos.clear()
        self._update_layers_transforms(asset.root_layers, project, QTransform())
        self._update_origin_marker()
        self._update_mesh_overlay()

    def _update_layers_transforms(self, layers: list[PaperDollLayer], project: Project, parent_tf: QTransform):
        for layer in layers:
            sox, soy = self._scale_offsets.get(layer.id, (0.0, 0.0))
            preview_sx = layer.scale_x + sox
            preview_sy = layer.scale_y + soy

            tf = QTransform()
            tf.translate(layer.x, layer.y)
            tf.translate(layer.origin_x, layer.origin_y)
            tf.rotate(layer.rotation)
            tf.scale(preview_sx, preview_sy)
            tf.translate(-layer.origin_x, -layer.origin_y)
            composed = tf * parent_tf

            # Update existing pixmap item position/rotation instead of recreating it
            item = self._pixmap_items.get(layer.id)
            if item:
                item.setTransform(composed)
                
                # Check for image swaps (like eye blinking)
                draw_image_id = self._image_swaps.get(layer.id, layer.image_id)
                if draw_image_id:
                    img = project.get_image(draw_image_id)
                    if img and img.path and os.path.isfile(img.path):
                        if img.path not in self._pixmap_cache:
                            self._pixmap_cache[img.path] = QPixmap(img.path)
                        cached_pix = self._pixmap_cache[img.path]
                        if item.pixmap().cacheKey() != cached_pix.cacheKey():
                            item.setPixmap(cached_pix)

            origin_scene = composed.map(QPointF(layer.origin_x, layer.origin_y))
            self._origin_scene_pos[layer.id] = origin_scene
            self._update_layers_transforms(layer.children, project, composed)

    def _draw_layers(self, layers: list[PaperDollLayer], project: Project, parent_tf: QTransform):
        for layer in layers:
            sox, soy = self._scale_offsets.get(layer.id, (0.0, 0.0))
            preview_sx = layer.scale_x + sox
            preview_sy = layer.scale_y + soy

            tf = QTransform()
            tf.translate(layer.x, layer.y)
            tf.translate(layer.origin_x, layer.origin_y)
            tf.rotate(layer.rotation)
            tf.scale(preview_sx, preview_sy)
            tf.translate(-layer.origin_x, -layer.origin_y)
            composed = tf * parent_tf

            draw_image_id = self._image_swaps.get(layer.id, layer.image_id)

            if draw_image_id:
                img = project.get_image(draw_image_id)
                if img and img.path and os.path.isfile(img.path):
                    if img.path not in self._pixmap_cache:
                        self._pixmap_cache[img.path] = QPixmap(img.path)

                    pix = self._pixmap_cache[img.path]
                    if not pix.isNull():
                        if layer.mesh_deform.enabled:
                            self._draw_mesh_layer(layer, pix, composed)
                        else:
                            item = self._scene.addPixmap(pix)
                            item.setTransform(composed)
                            item.setData(0, layer.id)
                            self._pixmap_items[layer.id] = item

            origin_scene = composed.map(QPointF(layer.origin_x, layer.origin_y))
            self._origin_scene_pos[layer.id] = origin_scene
            self._draw_layers(layer.children, project, composed)

    def _get_mesh_vert_positions(self, layer: PaperDollLayer, pix: QPixmap) -> list[QPointF]:
        """Get the absolute (local-space) positions of all mesh verts including offsets."""
        cfg = layer.mesh_deform
        cols, rows = cfg.grid_cols, cfg.grid_rows
        w, h = pix.width(), pix.height()
        offsets = self._mesh_offsets.get(layer.id, [])
        positions = []
        for r in range(rows + 1):
            for c in range(cols + 1):
                idx = r * (cols + 1) + c
                base_x = c * w / cols
                base_y = r * h / rows
                dx, dy = 0.0, 0.0
                if idx < len(offsets):
                    dx, dy = offsets[idx][0], offsets[idx][1]
                positions.append(QPointF(base_x + dx, base_y + dy))
        return positions

    def _draw_mesh_layer(self, layer: PaperDollLayer, pix: QPixmap, composed: QTransform):
        """Draw a mesh-deformed layer by rendering warped triangles onto a composited image.
        
        Each quad cell is split along the TL-BR diagonal into two triangles.
        Both triangles use shared vertices so there are no gaps between cells.
        The result is painted onto a single QImage and added to the scene.
        """
        from PySide6.QtGui import QPainterPath

        cfg = layer.mesh_deform
        cols, rows = cfg.grid_cols, cfg.grid_rows
        w, h = pix.width(), pix.height()
        source_image = pix.toImage()

        verts = self._get_mesh_vert_positions(layer, pix)

        # Map all verts to scene space so we know the bounding box for our output image
        scene_verts = [composed.map(v) for v in verts]
        min_x = min(p.x() for p in scene_verts)
        min_y = min(p.y() for p in scene_verts)
        max_x = max(p.x() for p in scene_verts)
        max_y = max(p.y() for p in scene_verts)

        out_w = int(max_x - min_x) + 4
        out_h = int(max_y - min_y) + 4
        if out_w < 1 or out_h < 1:
            return

        out_img = QImage(out_w, out_h, QImage.Format.Format_ARGB32)
        out_img.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out_img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Offset so scene min maps to image (2,2) with a little padding
        offset_x = min_x - 2
        offset_y = min_y - 2

        for r in range(rows):
            for c in range(cols):
                tl_i = r * (cols + 1) + c
                tr_i = tl_i + 1
                bl_i = (r + 1) * (cols + 1) + c
                br_i = bl_i + 1

                # Scene-space destination points
                s_tl = scene_verts[tl_i]
                s_tr = scene_verts[tr_i]
                s_bl = scene_verts[bl_i]
                s_br = scene_verts[br_i]

                # Translate to output image coords
                d_tl = QPointF(s_tl.x() - offset_x, s_tl.y() - offset_y)
                d_tr = QPointF(s_tr.x() - offset_x, s_tr.y() - offset_y)
                d_bl = QPointF(s_bl.x() - offset_x, s_bl.y() - offset_y)
                d_br = QPointF(s_br.x() - offset_x, s_br.y() - offset_y)

                # Source cell rect in the original image
                src_x = c * w / cols
                src_y = r * h / rows
                src_w = w / cols
                src_h = h / rows

                sub_img = source_image.copy(int(src_x), int(src_y), int(src_w), int(src_h))
                sw = float(sub_img.width())
                sh = float(sub_img.height())
                if sw < 1 or sh < 1:
                    continue

                # Upper triangle: source (0,0)-(sw,0)-(sw,sh) -> dest TL-TR-BR
                self._paint_mesh_triangle(
                    painter, sub_img,
                    QPointF(0, 0), QPointF(sw, 0), QPointF(sw, sh),
                    d_tl, d_tr, d_br
                )
                # Lower triangle: source (0,0)-(sw,sh)-(0,sh) -> dest TL-BR-BL
                self._paint_mesh_triangle(
                    painter, sub_img,
                    QPointF(0, 0), QPointF(sw, sh), QPointF(0, sh),
                    d_tl, d_br, d_bl
                )

        painter.end()

        result_pix = QPixmap.fromImage(out_img)
        item = self._scene.addPixmap(result_pix)
        # Position the output image at the scene-space min corner
        item.setPos(offset_x, offset_y)
        item.setData(0, layer.id)
        self._pixmap_items[layer.id] = item

    def _paint_mesh_triangle(self, painter: QPainter, sub_img: QImage,
                              sp0: QPointF, sp1: QPointF, sp2: QPointF,
                              dp0: QPointF, dp1: QPointF, dp2: QPointF):
        """Paint a single textured triangle using affine transform + clip path."""
        from PySide6.QtGui import QPainterPath

        # Compute affine: sp0->dp0, sp1->dp1, sp2->dp2
        sx1 = sp1.x() - sp0.x()
        sy1 = sp1.y() - sp0.y()
        sx2 = sp2.x() - sp0.x()
        sy2 = sp2.y() - sp0.y()

        det = sx1 * sy2 - sx2 * sy1
        if abs(det) < 1e-6:
            return

        dx1 = dp1.x() - dp0.x()
        dy1 = dp1.y() - dp0.y()
        dx2 = dp2.x() - dp0.x()
        dy2 = dp2.y() - dp0.y()

        inv_det = 1.0 / det
        a = (dx1 * sy2 - dx2 * sy1) * inv_det
        c_val = (dx2 * sx1 - dx1 * sx2) * inv_det
        b = (dy1 * sy2 - dy2 * sy1) * inv_det
        d_val = (dy2 * sx1 - dy1 * sx2) * inv_det
        tx = dp0.x() - a * sp0.x() - c_val * sp0.y()
        ty = dp0.y() - b * sp0.x() - d_val * sp0.y()

        tf = QTransform(a, b, c_val, d_val, tx, ty)

        # Clip to the destination triangle
        clip = QPainterPath()
        clip.moveTo(dp0)
        clip.lineTo(dp1)
        clip.lineTo(dp2)
        clip.closeSubpath()

        painter.save()
        painter.setClipPath(clip)
        painter.setTransform(tf, False)
        painter.drawImage(0, 0, sub_img)
        painter.restore()

    def _update_mesh_overlay(self):
        """Show/hide mesh vertex handles when a mesh-enabled layer is selected."""
        # Remove old handles and lines
        for item in self._mesh_vert_handles:
            if item.scene():
                self._scene.removeItem(item)
        self._mesh_vert_handles.clear()
        for item in self._mesh_line_items:
            if item.scene():
                self._scene.removeItem(item)
        self._mesh_line_items.clear()

        if self._exporting:
            return

        if not self._selected_layer_id:
            return

        # We need the asset to find the layer — check if we have a pixmap for it
        # The layer data is accessed via the tab, but we can get mesh info from stored state
        # We'll use a reference stored during rebuild
        if not hasattr(self, '_current_asset_ref') or not self._current_asset_ref:
            return
        layer = self._current_asset_ref.find_layer(self._selected_layer_id)
        if not layer or not layer.mesh_deform.enabled:
            return

        # Get the pixmap for dimensions
        draw_image_id = self._image_swaps.get(layer.id, layer.image_id)
        if not draw_image_id:
            return
        if not hasattr(self, '_current_project_ref') or not self._current_project_ref:
            return
        img = self._current_project_ref.get_image(draw_image_id)
        if not img or not img.path or not os.path.isfile(img.path):
            return
        if img.path not in self._pixmap_cache:
            self._pixmap_cache[img.path] = QPixmap(img.path)
        pix = self._pixmap_cache[img.path]
        if pix.isNull():
            return

        # Get the composed transform for this layer
        composed = self._get_layer_composed_transform(layer)
        if composed is None:
            return

        verts = self._get_mesh_vert_positions(layer, pix)
        cfg = layer.mesh_deform
        cols, rows = cfg.grid_cols, cfg.grid_rows

        # Draw grid lines
        line_pen = QPen(QColor("#44ff88"), 1.0, Qt.PenStyle.DotLine)
        for r in range(rows + 1):
            for c in range(cols):
                i1 = r * (cols + 1) + c
                i2 = i1 + 1
                p1 = composed.map(verts[i1])
                p2 = composed.map(verts[i2])
                line = self._scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(), line_pen)
                line.setZValue(1500)
                self._mesh_line_items.append(line)
        for c in range(cols + 1):
            for r in range(rows):
                i1 = r * (cols + 1) + c
                i2 = (r + 1) * (cols + 1) + c
                p1 = composed.map(verts[i1])
                p2 = composed.map(verts[i2])
                line = self._scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(), line_pen)
                line.setZValue(1500)
                self._mesh_line_items.append(line)

        # Draw vertex handles
        handle_pen = QPen(QColor("#44ff88"), 1.5)
        handle_brush = QBrush(QColor("#44ff8880"))
        hr = self.MESH_HANDLE_RADIUS
        for i, vert in enumerate(verts):
            scene_pt = composed.map(vert)
            handle = self._scene.addEllipse(
                scene_pt.x() - hr, scene_pt.y() - hr, hr * 2, hr * 2,
                handle_pen, handle_brush
            )
            handle.setZValue(2500)
            handle.setData(0, i)  # store vert index
            self._mesh_vert_handles.append(handle)

    def _get_layer_composed_transform(self, target_layer: PaperDollLayer) -> QTransform | None:
        """Walk the hierarchy to compute the composed world transform for a layer."""
        if not hasattr(self, '_current_asset_ref') or not self._current_asset_ref:
            return None
        path = self._find_layer_path(self._current_asset_ref.root_layers, target_layer.id)
        if path is None:
            return None
        composed = QTransform()
        for layer in path:
            sox, soy = self._scale_offsets.get(layer.id, (0.0, 0.0))
            tf = QTransform()
            tf.translate(layer.x, layer.y)
            tf.translate(layer.origin_x, layer.origin_y)
            tf.rotate(layer.rotation)
            tf.scale(layer.scale_x + sox, layer.scale_y + soy)
            tf.translate(-layer.origin_x, -layer.origin_y)
            composed = tf * composed
        return composed

    def _find_layer_path(self, layers: list[PaperDollLayer], target_id: str, path=None) -> list[PaperDollLayer] | None:
        """Find the path from root to the target layer (inclusive)."""
        if path is None:
            path = []
        for layer in layers:
            current_path = path + [layer]
            if layer.id == target_id:
                return current_path
            result = self._find_layer_path(layer.children, target_id, current_path)
            if result:
                return result
        return None

    def _update_origin_marker(self):
        if self._exporting:
            return
        if not self._selected_layer_id or self._selected_layer_id not in self._origin_scene_pos:
            for item in (self._origin_circle, self._origin_hline, self._origin_vline):
                if item and item.scene():
                    item.setVisible(False)
            return

        pos = self._origin_scene_pos[self._selected_layer_id]
        r = self.ORIGIN_SIZE
        arm = r + 6
        pen = QPen(QColor("#ff4488"), 2.0)
        fill = QBrush(QColor("#ff448860"))

        if not self._origin_circle or not self._origin_circle.scene():
            self._origin_circle = self._scene.addEllipse(0, 0, r * 2, r * 2, pen, fill)
            self._origin_circle.setZValue(2000)
            self._origin_hline = self._scene.addLine(0, 0, 0, 0, pen)
            self._origin_hline.setZValue(2000)
            self._origin_vline = self._scene.addLine(0, 0, 0, 0, pen)
            self._origin_vline.setZValue(2000)

        self._origin_circle.setVisible(True)
        self._origin_circle.setRect(pos.x() - r, pos.y() - r, r * 2, r * 2)
        self._origin_hline.setVisible(True)
        self._origin_hline.setLine(pos.x() - arm, pos.y(), pos.x() + arm, pos.y())
        self._origin_vline.setVisible(True)
        self._origin_vline.setLine(pos.x(), pos.y() - arm, pos.x(), pos.y() + arm)

    def _hit_mesh_vert(self, scene_pos: QPointF) -> int | None:
        """Check if scene_pos hits a mesh vertex handle. Returns vert index or None."""
        hr = self.MESH_HANDLE_RADIUS + 4  # generous hit radius
        for i, handle in enumerate(self._mesh_vert_handles):
            center_x = handle.rect().center().x()
            center_y = handle.rect().center().y()
            dx = scene_pos.x() - center_x
            dy = scene_pos.y() - center_y
            if dx * dx + dy * dy <= hr * hr:
                return i
        return None

    def _hit_mesh_cell(self, scene_pos: QPointF) -> tuple[int, int] | None:
        """Check if scene_pos is inside a mesh grid cell. Returns (row, col) or None."""
        if not self._mesh_vert_handles or not self._selected_layer_id:
            return None
        if not hasattr(self, '_current_asset_ref') or not self._current_asset_ref:
            return None
        layer = self._current_asset_ref.find_layer(self._selected_layer_id)
        if not layer or not layer.mesh_deform.enabled:
            return None

        cfg = layer.mesh_deform
        cols, rows = cfg.grid_cols, cfg.grid_rows

        # Get scene-space vert positions from handles
        for r in range(rows):
            for c in range(cols):
                tl_i = r * (cols + 1) + c
                tr_i = tl_i + 1
                bl_i = (r + 1) * (cols + 1) + c
                br_i = bl_i + 1
                if br_i >= len(self._mesh_vert_handles):
                    continue
                tl = self._mesh_vert_handles[tl_i].rect().center()
                tr = self._mesh_vert_handles[tr_i].rect().center()
                bl = self._mesh_vert_handles[bl_i].rect().center()
                br = self._mesh_vert_handles[br_i].rect().center()
                quad = QPolygonF([
                    QPointF(tl.x(), tl.y()), QPointF(tr.x(), tr.y()),
                    QPointF(br.x(), br.y()), QPointF(bl.x(), bl.y()),
                ])
                if quad.containsPoint(scene_pos, Qt.FillRule.OddEvenFill):
                    return (r, c)
        return None

    def _vert_index_to_cell(self, vert_idx: int) -> tuple[int, int] | None:
        """Given a flat vert index, return a reasonable cell (row, col) it belongs to."""
        if not self._selected_layer_id or not hasattr(self, '_current_asset_ref') or not self._current_asset_ref:
            return None
        layer = self._current_asset_ref.find_layer(self._selected_layer_id)
        if not layer or not layer.mesh_deform.enabled:
            return None
        cols = layer.mesh_deform.grid_cols
        rows = layer.mesh_deform.grid_rows
        # Vert is at grid position (vr, vc) where vr = idx // (cols+1), vc = idx % (cols+1)
        vr = vert_idx // (cols + 1)
        vc = vert_idx % (cols + 1)
        # Pick the cell to the top-left of this vert, clamped
        cr = min(vr, rows - 1)
        cc = min(vc, cols - 1)
        return (cr, cc)

    def _hit_origin(self, scene_pos: QPointF) -> bool:
        if not self._selected_layer_id or self._selected_layer_id not in self._origin_scene_pos:
            return False
        origin = self._origin_scene_pos[self._selected_layer_id]
        dx = scene_pos.x() - origin.x()
        dy = scene_pos.y() - origin.y()
        return (dx * dx + dy * dy) <= (self.ORIGIN_SIZE + 8) ** 2

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        scene_pos = self.mapToScene(event.pos())

        # Check mesh vert handles first
        vert_idx = self._hit_mesh_vert(scene_pos)
        if vert_idx is not None:
            self._dragging = "mesh_vert"
            self._dragging_vert_index = vert_idx
            self._drag_start_pos = scene_pos
            # Also figure out which cell this vert belongs to and select it
            cell = self._vert_index_to_cell(vert_idx)
            if cell:
                self.mesh_cell_clicked.emit(cell[0], cell[1])
            return

        # Check mesh cell click (inside a mesh grid cell)
        cell = self._hit_mesh_cell(scene_pos)
        if cell is not None:
            self.mesh_cell_clicked.emit(cell[0], cell[1])
            self.update()
            return

        if self._hit_origin(scene_pos):
            self._dragging = "origin"
            self._drag_layer_id = self._selected_layer_id
            self._drag_start_pos = scene_pos
            return
        for lid, item in reversed(list(self._pixmap_items.items())):
            if item.contains(item.mapFromScene(scene_pos)):
                self._dragging = "layer"
                self._drag_layer_id = lid
                self._drag_start_pos = scene_pos
                self.layer_clicked.emit(lid)
                return
        # Clicked outside everything — deselect mesh cell
        self.mesh_cell_clicked.emit(-1, -1)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self._dragging:
            return super().mouseMoveEvent(event)
        scene_pos = self.mapToScene(event.pos())
        dx = scene_pos.x() - self._drag_start_pos.x()
        dy = scene_pos.y() - self._drag_start_pos.y()

        if self._dragging == "mesh_vert" and self._dragging_vert_index is not None and self._selected_layer_id:
            self.mesh_vert_moved.emit(self._selected_layer_id, self._dragging_vert_index, dx, dy)
            self._drag_start_pos = scene_pos
        elif self._dragging == "layer" and self._drag_layer_id:
            self.layer_moved.emit(self._drag_layer_id, dx, dy)
            self._drag_start_pos = scene_pos
        elif self._dragging == "origin" and self._drag_layer_id:
            self.origin_moved.emit(self._drag_layer_id, dx, dy)
            self._drag_start_pos = scene_pos

    def mouseReleaseEvent(self, event):
        self._dragging = None
        self._drag_layer_id = None
        self._dragging_vert_index = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


# ── Timeline Panel ─────────────────────────────────────────────

class KeyframeTrack(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(20)
        self._keyframe_positions: list[float] =[]

    def set_keyframes(self, positions: list[float]):
        self._keyframe_positions = positions
        self.update()

    def paintEvent(self, event):
        if not self._keyframe_positions:
            return
        from PySide6.QtGui import QPainter as _P, QPolygonF
        p = _P(self)
        p.setRenderHint(_P.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ACCENT))

        w = self.width() - 14
        offset = 7
        size = 5
        for norm in self._keyframe_positions:
            cx = offset + norm * w
            cy = self.height() / 2.0
            diamond = QPolygonF([
                QPointF(cx, cy - size), QPointF(cx + size, cy),
                QPointF(cx, cy + size), QPointF(cx - size, cy),
            ])
            p.drawPolygon(diamond)
        p.end()

class TimelinePanel(QFrame):
    play_toggled = Signal(bool)
    time_scrubbed = Signal(float)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(130)
        self.setStyleSheet(f"background: {PANEL}; border-top: 2px solid {BORDER};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        top = QHBoxLayout()
        self.macro_label = QLabel("NO MACRO SELECTED")
        self.macro_label.setStyleSheet(f"color: {DIM}; font-size: 10px; font-weight: 700; letter-spacing: 1px;")
        top.addWidget(self.macro_label)
        top.addStretch()
        self.btn_prev = _btn("◀", icon_style=True)
        self.btn_play = _btn("▶ PLAY", accent=True)
        self.btn_next = _btn("▶", icon_style=True)
        self.btn_play.setCheckable(True)
        self.btn_play.toggled.connect(self.play_toggled.emit)
        top.addWidget(self.btn_prev)
        top.addWidget(self.btn_play)
        top.addWidget(self.btn_next)
        self.time_label = QLabel("0.00 / 0.00")
        self.time_label.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        top.addWidget(self.time_label)
        layout.addLayout(top)

        self.keyframe_track = KeyframeTrack()
        layout.addWidget(self.keyframe_track)

        self.seeker = QSlider(Qt.Orientation.Horizontal)
        self.seeker.setRange(0, 1000)
        self.seeker.setStyleSheet(f"""
            QSlider::groove:horizontal {{ background: {DARK}; height: 6px; border-radius: 3px; }}
            QSlider::handle:horizontal {{ background: {ACCENT}; width: 14px; margin: -4px 0; border-radius: 7px; }}
        """)
        self.seeker.valueChanged.connect(lambda v: self.time_scrubbed.emit(v / 1000.0))
        layout.addWidget(self.seeker)

    def set_macro(self, macro: PaperDollMacro | None):
        if macro:
            self.macro_label.setText(f"MACRO: {macro.name.upper()}")
            self.time_label.setText(f"0.00 / {macro.duration:.2f}")
            self._update_keyframe_track(macro)
        else:
            self.macro_label.setText("NO MACRO SELECTED")
            self.time_label.setText("0.00 / 0.00")
            self.keyframe_track.set_keyframes([])

    def set_time(self, current: float, duration: float):
        self.time_label.setText(f"{current:.2f} / {duration:.2f}")
        if duration > 0:
            self.seeker.blockSignals(True)
            self.seeker.setValue(int((current / duration) * 1000))
            self.seeker.blockSignals(False)

    def update_keyframes(self, macro: PaperDollMacro | None):
        self._update_keyframe_track(macro)

    def _update_keyframe_track(self, macro: PaperDollMacro | None):
        if not macro or macro.duration <= 0:
            self.keyframe_track.set_keyframes([])
            return
        all_kf = not macro.keyframes and not macro.mesh_keyframes
        if all_kf:
            self.keyframe_track.set_keyframes([])
            return
        times = set(k.time for k in macro.keyframes)
        times.update(mk.time for mk in macro.mesh_keyframes)
        positions = [t / macro.duration for t in sorted(times)]
        self.keyframe_track.set_keyframes(positions)


# ── Behavior Config Dialog ─────────────────────────────────────

class BehaviorConfigDialog(QDialog):
    """Popup dialog for configuring blink or idle breathing."""
    def __init__(self, asset: PaperDollAsset, mode: str, project: Project, parent=None):
        super().__init__(parent)
        self.asset = asset
        self.project = project
        self.mode = mode
        self.setWindowTitle(f"Configure {mode.title()}")
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(f"background: {PANEL}; color: {TEXT};")
        self._alt_image_id: str | None = None
        self._build_ui()

    def _collect_layers(self, layers, depth=0):
        result =[]
        for l in layers:
            result.append((l.id, "  " * depth + l.name))
            result += self._collect_layers(l.children, depth + 1)
        return result

    def _make_image_row(self, current_image_id: str | None):
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        self._alt_image_label = QLabel("(none)")
        self._alt_image_label.setStyleSheet(f"color: {TEXT}; padding: 2px 6px; background: {SURF2}; border: 1px solid {BORDER};")
        self._alt_image_label.setMinimumWidth(160)
        if current_image_id:
            self._alt_image_id = current_image_id
            img = self.project.get_image(current_image_id)
            if img:
                self._alt_image_label.setText(img.name)
        browse_btn = _btn("Browse…")
        browse_btn.clicked.connect(self._browse_alt_image)
        pick_btn = _btn("Pick…")
        pick_btn.clicked.connect(self._pick_alt_image)
        h.addWidget(self._alt_image_label, stretch=1)
        h.addWidget(pick_btn)
        h.addWidget(browse_btn)
        return container

    def _browse_alt_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Alternate Image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path: return
        name = os.path.splitext(os.path.basename(path))[0]
        img = RegisteredImage(name=name, path=path, category="character")
        self.project.images.append(img)
        self._alt_image_id = img.id
        self._alt_image_label.setText(img.name)

    def _pick_alt_image(self):
        if not self.project.images:
            QMessageBox.information(self, "No Images", "No registered images yet. Use Browse to add one.")
            return
        choices =[img.name for img in self.project.images]
        choice, ok = QInputDialog.getItem(self, "Pick Image", "Select image:", choices, 0, False)
        if not ok: return
        idx = choices.index(choice)
        img = self.project.images[idx]
        self._alt_image_id = img.id
        self._alt_image_label.setText(img.name)

    def _build_ui(self):
        layout = QFormLayout(self)
        layout.setSpacing(8)
        all_layers = self._collect_layers(self.asset.root_layers)

        if self.mode == "blink":
            cfg = self.asset.blink
            self.enabled_cb = QCheckBox("Enabled")
            self.enabled_cb.setChecked(cfg.enabled)
            layout.addRow(self.enabled_cb)

            self.layer_combo = QComboBox()
            for lid, lname in all_layers:
                self.layer_combo.addItem(lname, lid)
            idx = self.layer_combo.findData(cfg.layer_id)
            if idx >= 0: self.layer_combo.setCurrentIndex(idx)
            layout.addRow("Target Layer:", self.layer_combo)
            layout.addRow("Alt Image (closed):", self._make_image_row(cfg.alt_image_id))

            self.interval_min_spin = _make_spin(cfg.interval_min, 0.1, 30.0, 0.1)
            layout.addRow("Interval Min (s):", self.interval_min_spin)
            self.interval_max_spin = _make_spin(cfg.interval_max, 0.1, 30.0, 0.1)
            layout.addRow("Interval Max (s):", self.interval_max_spin)
            self.duration_spin = _make_spin(cfg.blink_duration, 0.01, 2.0, 0.01, 2)
            layout.addRow("Blink Duration (s):", self.duration_spin)

        elif self.mode == "idle":
            cfg = self.asset.idle_breathing
            self.enabled_cb = QCheckBox("Enabled")
            self.enabled_cb.setChecked(cfg.enabled)
            layout.addRow(self.enabled_cb)

            self.layer_combo = QComboBox()
            self.layer_combo.addItem("(Root — all layers)", "")
            for lid, lname in all_layers:
                self.layer_combo.addItem(lname, lid)
            idx = self.layer_combo.findData(cfg.layer_id)
            if idx >= 0: self.layer_combo.setCurrentIndex(idx)
            layout.addRow("Target Layer:", self.layer_combo)

            self.scale_spin = _make_spin(cfg.scale_amount, 0.001, 0.5, 0.005, 3)
            layout.addRow("Scale Amount:", self.scale_spin)
            self.speed_spin = _make_spin(cfg.speed, 0.5, 20.0, 0.5)
            layout.addRow("Cycle Speed (s):", self.speed_spin)
            self.children_cb = QCheckBox("Affect Children")
            self.children_cb.setChecked(cfg.affect_children)
            layout.addRow(self.children_cb)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def apply(self):
        if self.mode == "blink":
            cfg = self.asset.blink
            cfg.enabled = self.enabled_cb.isChecked()
            cfg.layer_id = self.layer_combo.currentData() or ""
            cfg.alt_image_id = self._alt_image_id
            cfg.interval_min = self.interval_min_spin.value()
            cfg.interval_max = self.interval_max_spin.value()
            cfg.blink_duration = self.duration_spin.value()
        elif self.mode == "idle":
            cfg = self.asset.idle_breathing
            cfg.enabled = self.enabled_cb.isChecked()
            cfg.layer_id = self.layer_combo.currentData() or ""
            cfg.scale_amount = self.scale_spin.value()
            cfg.speed = self.speed_spin.value()
            cfg.affect_children = self.children_cb.isChecked()


# ── Main Tab Widget ────────────────────────────────────────────

class PaperDollTab(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project: Project | None = None
        self._current_asset: PaperDollAsset | None = None
        self._selected_layer: PaperDollLayer | None = None
        self._selected_mesh_cell: tuple[int, int] | None = None  # (row, col) of selected grid cell
        self._current_macro: PaperDollMacro | None = None
        self._playback_time: float = 0.0
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(16)
        self._playback_timer.timeout.connect(self._tick_playback)
        self._suppress_signals = False

        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(16)
        self._preview_timer.timeout.connect(self._tick_preview)
        self._preview_idle = False
        self._preview_blink = False
        self._preview_time: float = 0.0
        
        self._blink_next: float = 0.0
        self._blink_active: bool = False
        self._blink_end: float = 0.0
        
        self._preview_image_swaps: dict[str, str] = {}
        self._preview_scale_offsets: dict[str, tuple[float, float]] = {}

        self._build_ui()

    def load_project(self, project: Project):
        self.project = project
        self._refresh_asset_combo()
        if project.paper_dolls:
            self._current_asset = project.paper_dolls[0]
            self.asset_combo.setCurrentIndex(0)
        else:
            self._current_asset = None
        self._refresh_all()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Asset selector bar ──
        asset_bar = QHBoxLayout()
        asset_bar.setContentsMargins(10, 6, 10, 6)
        asset_bar.addWidget(QLabel("Animation Asset:"))
        
        self.asset_combo = QComboBox()
        self.asset_combo.setMinimumWidth(200)
        self.asset_combo.currentIndexChanged.connect(self._on_asset_changed)
        asset_bar.addWidget(self.asset_combo)
        
        self.btn_new_asset = _btn("+ New", accent=True)
        self.btn_new_asset.clicked.connect(self._new_asset)
        asset_bar.addWidget(self.btn_new_asset)
        
        self.btn_rename_asset = _btn("Rename")
        self.btn_rename_asset.clicked.connect(self._rename_asset)
        asset_bar.addWidget(self.btn_rename_asset)
        
        self.btn_delete_asset = _btn("Delete")
        self.btn_delete_asset.clicked.connect(self._delete_asset)
        asset_bar.addWidget(self.btn_delete_asset)
        
        asset_bar.addStretch()

        # Save/Load Project for standalone capability
        self.btn_save = _btn("Save Project")
        self.btn_save.clicked.connect(self._save_project)
        self.btn_load = _btn("Load Project")
        self.btn_load.clicked.connect(self._load_project)
        asset_bar.addWidget(self.btn_load)
        asset_bar.addWidget(self.btn_save)

        root.addLayout(asset_bar)

        upper = QHBoxLayout()

        # LEFT: Hierarchy
        left_panel = QWidget()
        left_panel.setFixedWidth(280)
        left_panel.setStyleSheet(f"background: {PANEL}; border-right: 1px solid {BORDER};")
        left_vbox = QVBoxLayout(left_panel)
        left_vbox.setContentsMargins(8, 8, 8, 8)
        left_vbox.addWidget(_section("Hierarchy & Parenting"))

        topo_bar = QHBoxLayout()
        self.btn_move_up = _btn("↑", icon_style=True)
        self.btn_move_down = _btn("↓", icon_style=True)
        self.btn_unparent = _btn("←", icon_style=True)
        self.btn_reparent = _btn("→", icon_style=True)
        self.btn_delete_layer = _btn("DEL", icon_style=True)
        self.btn_move_up.clicked.connect(self._move_layer_up)
        self.btn_move_down.clicked.connect(self._move_layer_down)
        self.btn_unparent.clicked.connect(self._unparent_layer)
        self.btn_reparent.clicked.connect(self._reparent_layer)
        self.btn_delete_layer.clicked.connect(self._delete_layer)
        for b in[self.btn_move_up, self.btn_move_down, self.btn_unparent, self.btn_reparent]:
            topo_bar.addWidget(b)
        topo_bar.addStretch()
        topo_bar.addWidget(self.btn_delete_layer)
        left_vbox.addLayout(topo_bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setStyleSheet(f"background: {SURFACE}; border: 1px solid {BORDER};")
        self.tree.currentItemChanged.connect(self._on_tree_selection_changed)
        left_vbox.addWidget(self.tree)

        self.btn_add_layer = _btn("+ Add Layer from Image…", accent=True)
        self.btn_add_layer.clicked.connect(self._add_layer_from_image)
        left_vbox.addWidget(self.btn_add_layer)
        upper.addWidget(left_panel)

        # CENTER: Canvas
        canvas_container = QWidget()
        canvas_vbox = QVBoxLayout(canvas_container)
        canvas_vbox.setContentsMargins(4, 4, 4, 4)
        self.canvas = PaperDollCanvas()
        self.canvas.layer_moved.connect(self._on_canvas_layer_moved)
        self.canvas.origin_moved.connect(self._on_canvas_origin_moved)
        self.canvas.layer_clicked.connect(self._on_canvas_layer_clicked)
        self.canvas.mesh_vert_moved.connect(self._on_canvas_mesh_vert_moved)
        self.canvas.mesh_cell_clicked.connect(self._on_mesh_cell_clicked)
        canvas_vbox.addWidget(self.canvas)
        upper.addWidget(canvas_container, stretch=1)

        # RIGHT: Properties & Macros (scrollable)
        right_scroll = QScrollArea()
        right_scroll.setFixedWidth(310)
        right_scroll.setWidgetResizable(True)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setStyleSheet(f"background: {PANEL}; border-left: 1px solid {BORDER};")
        right_panel = QWidget()
        right_panel.setMinimumWidth(280)
        right_vbox = QVBoxLayout(right_panel)
        right_vbox.setContentsMargins(8, 8, 8, 8)
        right_vbox.setSpacing(4)

        right_vbox.addWidget(_section("Selected Layer"))
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.layer_name_edit = QLineEdit()
        self.layer_name_edit.setStyleSheet(f"background: {SURF2}; border: 1px solid {BORDER}; color: {TEXT}; padding: 3px;")
        self.layer_name_edit.editingFinished.connect(self._on_layer_name_changed)
        name_row.addWidget(self.layer_name_edit)
        right_vbox.addLayout(name_row)

        prop_frame = QFrame()
        prop_frame.setStyleSheet(f"background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 4px;")
        pf_layout = QVBoxLayout(prop_frame)
        pf_layout.setContentsMargins(6, 6, 6, 6)

        self.prop_spins: dict[str, QDoubleSpinBox] = {}
        self.prop_diamonds: dict[str, QPushButton] = {}
        for prop_name, default_val in[("X Offset", 0.0), ("Y Offset", 0.0), ("Rotation", 0.0), ("Scale X", 1.0), ("Scale Y", 1.0)]:
            row = QHBoxLayout()
            row.setContentsMargins(2, 2, 2, 2)
            diamond = _keyframe_diamond()
            diamond.setProperty("prop_name", prop_name)
            diamond.clicked.connect(self._on_keyframe_diamond_clicked)
            row.addWidget(diamond)
            row.addWidget(QLabel(prop_name))
            if prop_name in ("Scale X", "Scale Y"):
                spin = _make_spin(default_val, 0.01, 50.0, 0.05, 2)
            elif prop_name == "Rotation":
                spin = _make_spin(default_val, -360.0, 360.0, 1.0, 1)
            else:
                spin = _make_spin(default_val, -9999.0, 9999.0, 1.0, 1)
            spin.valueChanged.connect(self._on_property_spin_changed)
            spin.setProperty("prop_name", prop_name)
            row.addWidget(spin)
            self.prop_spins[prop_name] = spin
            self.prop_diamonds[prop_name] = diamond
            pf_layout.addLayout(row)

        origin_row = QHBoxLayout()
        origin_row.setContentsMargins(2, 6, 2, 2)
        origin_row.addWidget(QLabel("Origin:"))
        self.origin_x_spin = _make_spin(0.0, -9999, 9999, 1.0, 1)
        self.origin_y_spin = _make_spin(0.0, -9999, 9999, 1.0, 1)
        self.origin_x_spin.valueChanged.connect(self._on_origin_changed)
        self.origin_y_spin.valueChanged.connect(self._on_origin_changed)
        origin_row.addWidget(QLabel("X"))
        origin_row.addWidget(self.origin_x_spin)
        origin_row.addWidget(QLabel("Y"))
        origin_row.addWidget(self.origin_y_spin)
        pf_layout.addLayout(origin_row)

        right_vbox.addWidget(prop_frame)

        # -- Mesh Deform --
        right_vbox.addWidget(_section("Mesh Deform"))
        mesh_frame = QFrame()
        mesh_frame.setStyleSheet(f"background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 4px;")
        mf_layout = QVBoxLayout(mesh_frame)
        mf_layout.setContentsMargins(6, 6, 6, 6)

        mesh_enable_row = QHBoxLayout()
        self.mesh_enable_cb = QCheckBox("Enable Mesh")
        self.mesh_enable_cb.toggled.connect(self._on_mesh_enable_toggled)
        mesh_enable_row.addWidget(self.mesh_enable_cb)
        mesh_enable_row.addStretch()
        self.btn_mesh_reset = _btn("Reset Grid")
        self.btn_mesh_reset.clicked.connect(self._on_mesh_reset)
        mesh_enable_row.addWidget(self.btn_mesh_reset)
        mf_layout.addLayout(mesh_enable_row)

        mesh_grid_row = QHBoxLayout()
        mesh_grid_row.addWidget(QLabel("Cols:"))
        self.mesh_cols_spin = _make_spin(4, 1, 16, 1, 0)
        self.mesh_cols_spin.valueChanged.connect(self._on_mesh_grid_changed)
        mesh_grid_row.addWidget(self.mesh_cols_spin)
        mesh_grid_row.addWidget(QLabel("Rows:"))
        self.mesh_rows_spin = _make_spin(4, 1, 16, 1, 0)
        self.mesh_rows_spin.valueChanged.connect(self._on_mesh_grid_changed)
        mesh_grid_row.addWidget(self.mesh_rows_spin)
        mf_layout.addLayout(mesh_grid_row)

        # Cell inspector header
        self.mesh_cell_label = QLabel("No cell selected")
        self.mesh_cell_label.setStyleSheet(f"color: {DIM}; font-size: 10px; font-weight: 600; padding: 4px 0 2px 0;")
        mf_layout.addWidget(self.mesh_cell_label)

        # 4 corner spinbox pairs (TL, TR, BL, BR) with keyframe diamonds
        self.mesh_corner_spins: dict[str, tuple[QDoubleSpinBox, QDoubleSpinBox]] = {}
        self.mesh_corner_diamonds: dict[str, QPushButton] = {}
        for corner in ("TL", "TR", "BL", "BR"):
            row = QHBoxLayout()
            row.setContentsMargins(2, 1, 2, 1)
            diamond = _keyframe_diamond()
            diamond.setProperty("mesh_corner", corner)
            diamond.clicked.connect(self._on_mesh_cell_keyframe_diamond_clicked)
            row.addWidget(diamond)
            lbl = QLabel(corner)
            lbl.setFixedWidth(20)
            row.addWidget(lbl)
            sx = _make_spin(0.0, -9999.0, 9999.0, 1.0, 1)
            sy = _make_spin(0.0, -9999.0, 9999.0, 1.0, 1)
            sx.setProperty("mesh_corner", corner)
            sx.setProperty("mesh_axis", "x")
            sy.setProperty("mesh_corner", corner)
            sy.setProperty("mesh_axis", "y")
            sx.valueChanged.connect(self._on_mesh_corner_spin_changed)
            sy.valueChanged.connect(self._on_mesh_corner_spin_changed)
            row.addWidget(QLabel("X"))
            row.addWidget(sx)
            row.addWidget(QLabel("Y"))
            row.addWidget(sy)
            self.mesh_corner_spins[corner] = (sx, sy)
            self.mesh_corner_diamonds[corner] = diamond
            mf_layout.addLayout(row)

        # Snapshot-all-verts keyframe button
        mesh_snap_row = QHBoxLayout()
        self.mesh_kf_diamond = _keyframe_diamond()
        self.mesh_kf_diamond.clicked.connect(self._on_mesh_keyframe_diamond_clicked)
        mesh_snap_row.addWidget(self.mesh_kf_diamond)
        mesh_snap_row.addWidget(QLabel("Snapshot All Verts"))
        mesh_snap_row.addStretch()
        mf_layout.addLayout(mesh_snap_row)

        right_vbox.addWidget(mesh_frame)

        # -- Behaviors (collapsible) --
        self.behaviors_section = CollapsibleSection("Behaviors")
        bv = self.behaviors_section.content_layout()

        blink_row = QHBoxLayout()
        blink_row.setSpacing(4)
        self.btn_config_blink = _btn("Blink…")
        self.btn_config_blink.clicked.connect(lambda: self._open_behavior_dialog("blink"))
        self.btn_preview_blink = _btn("▶ Preview", icon_style=True)
        self.btn_preview_blink.setCheckable(True)
        self.btn_preview_blink.toggled.connect(self._toggle_preview_blink)
        blink_row.addWidget(self.btn_config_blink)
        blink_row.addWidget(self.btn_preview_blink)
        bv.addLayout(blink_row)

        idle_row = QHBoxLayout()
        idle_row.setSpacing(4)
        self.btn_config_idle = _btn("Idle…")
        self.btn_config_idle.clicked.connect(lambda: self._open_behavior_dialog("idle"))
        self.btn_preview_idle = _btn("▶ Preview", icon_style=True)
        self.btn_preview_idle.setCheckable(True)
        self.btn_preview_idle.toggled.connect(self._toggle_preview_idle)
        idle_row.addWidget(self.btn_config_idle)
        idle_row.addWidget(self.btn_preview_idle)
        bv.addLayout(idle_row)
        right_vbox.addWidget(self.behaviors_section)

        # -- Macros (collapsible) --
        self.macros_section = CollapsibleSection("Macros")
        self.macros_section.set_expanded(True)
        mv = self.macros_section.content_layout()

        self.macro_list = QTreeWidget()
        self.macro_list.setHeaderHidden(True)
        self.macro_list.setMaximumHeight(160)
        self.macro_list.setStyleSheet(f"background: {SURFACE}; border: 1px solid {BORDER};")
        self.macro_list.currentItemChanged.connect(self._on_macro_selection_changed)
        mv.addWidget(self.macro_list)

        macro_btns = QHBoxLayout()
        self.btn_new_macro = _btn("+ New Macro", accent=True)
        self.btn_new_macro.clicked.connect(self._new_macro)
        self.btn_rename_macro = _btn("Rename")
        self.btn_rename_macro.clicked.connect(self._rename_macro)
        self.btn_delete_macro = _btn("Delete")
        self.btn_delete_macro.clicked.connect(self._delete_macro)
        macro_btns.addWidget(self.btn_new_macro)
        macro_btns.addWidget(self.btn_rename_macro)
        macro_btns.addWidget(self.btn_delete_macro)
        mv.addLayout(macro_btns)

        dur_row = QHBoxLayout()
        dur_row.addWidget(QLabel("Duration (s):"))
        self.macro_duration_spin = _make_spin(1.0, 0.1, 60.0, 0.1)
        self.macro_duration_spin.valueChanged.connect(self._on_macro_duration_changed)
        dur_row.addWidget(self.macro_duration_spin)
        self.macro_loop_cb = QCheckBox("Loop")
        self.macro_loop_cb.toggled.connect(self._on_macro_loop_changed)
        dur_row.addWidget(self.macro_loop_cb)
        mv.addLayout(dur_row)

        # -- Export Macro --
        export_row = QHBoxLayout()
        self.btn_export_macro = _btn("Export PNG Sequence", accent=True)
        self.btn_export_macro.clicked.connect(self._export_macro_pngs)
        export_row.addWidget(self.btn_export_macro)
        mv.addLayout(export_row)
        right_vbox.addWidget(self.macros_section)

        right_vbox.addStretch()
        right_scroll.setWidget(right_panel)
        upper.addWidget(right_scroll)

        root.addLayout(upper, stretch=1)

        # ── Timeline ──
        self.timeline = TimelinePanel()
        self.timeline.play_toggled.connect(self._on_play_toggled)
        self.timeline.time_scrubbed.connect(self._on_time_scrubbed)
        self.timeline.btn_prev.clicked.connect(self._keyframe_prev)
        self.timeline.btn_next.clicked.connect(self._keyframe_next)
        root.addWidget(self.timeline)

    # ── Project Saving/Loading ─────────────────────────────────
    
    def _save_project(self):
        if not self.project: return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Project", "", "JSON Files (*.json)")
        if not file_path: return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.project.to_dict(), f, indent=2)
            QMessageBox.information(self, "Success", "Project saved successfully!")
            self._mark_changed()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save:\n{e}")

    def _load_project(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Load Project", "", "JSON Files (*.json)")
        if not file_path: return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            p = Project.from_dict(d)
            self.load_project(p)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load:\n{e}")

    # ── Asset management ───────────────────────────────────────

    def _refresh_asset_combo(self):
        self.asset_combo.blockSignals(True)
        self.asset_combo.clear()
        if self.project:
            for a in self.project.paper_dolls:
                self.asset_combo.addItem(a.name, a.id)
        self.asset_combo.blockSignals(False)

    def _on_asset_changed(self, idx):
        if not self.project or idx < 0:
            self._current_asset = None
        else:
            aid = self.asset_combo.itemData(idx)
            self._current_asset = self.project.get_paper_doll(aid)
        self._selected_layer = None
        self._selected_mesh_cell = None
        self._current_macro = None
        self._refresh_all()

    def _new_asset(self):
        if not self.project: return
        name, ok = QInputDialog.getText(self, "New Animation", "Name:")
        if not ok or not name.strip(): return
        asset = PaperDollAsset(name=name.strip())
        self.project.paper_dolls.append(asset)
        self._current_asset = asset
        self._selected_layer = None
        self._current_macro = None
        self._refresh_asset_combo()
        self.asset_combo.blockSignals(True)
        self.asset_combo.setCurrentIndex(len(self.project.paper_dolls) - 1)
        self.asset_combo.blockSignals(False)
        self._refresh_all()
        self._mark_changed()

    def _rename_asset(self):
        if not self._current_asset: return
        name, ok = QInputDialog.getText(self, "Rename", "New name:", text=self._current_asset.name)
        if ok and name.strip():
            self._current_asset.name = name.strip()
            idx = self.asset_combo.currentIndex()
            self.asset_combo.setItemText(idx, name.strip())
            self._mark_changed()

    def _delete_asset(self):
        if not self._current_asset or not self.project: return
        r = QMessageBox.question(self, "Delete", f"Delete '{self._current_asset.name}'?")
        if r != QMessageBox.StandardButton.Yes: return
        self.project.paper_dolls.remove(self._current_asset)
        self._current_asset = None
        self._selected_layer = None
        self._refresh_asset_combo()
        if self.project.paper_dolls: self.asset_combo.setCurrentIndex(0)
        self._refresh_all()
        self._mark_changed()

    # ── Hierarchy management ───────────────────────────────────

    def _refresh_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        if self._current_asset:
            self._populate_tree(self._current_asset.root_layers, self.tree.invisibleRootItem())
        self.tree.expandAll()
        if self._selected_layer:
            self._select_tree_item(self._selected_layer.id)
        self.tree.blockSignals(False)

    def _populate_tree(self, layers: list[PaperDollLayer], parent_item):
        for layer in layers:
            item = QTreeWidgetItem(parent_item, [layer.name])
            item.setData(0, Qt.ItemDataRole.UserRole, layer.id)
            self._populate_tree(layer.children, item)

    def _select_tree_item(self, layer_id: str):
        def _find(parent, lid):
            for i in range(parent.childCount()):
                child = parent.child(i)
                if child.data(0, Qt.ItemDataRole.UserRole) == lid: return child
                found = _find(child, lid)
                if found: return found
            return None
        item = _find(self.tree.invisibleRootItem(), layer_id)
        if item: self.tree.setCurrentItem(item)

    def _on_tree_selection_changed(self, current, previous):
        if not current or not self._current_asset:
            self._selected_layer = None
        else:
            lid = current.data(0, Qt.ItemDataRole.UserRole)
            self._selected_layer = self._current_asset.find_layer(lid)
        self._selected_mesh_cell = None
        self._refresh_properties()
        self.canvas.set_selected_layer(self._selected_layer.id if self._selected_layer else None)

    def _find_layer_parent_and_list(self, layer_id: str, layers=None, parent=None):
        if layers is None:
            layers = self._current_asset.root_layers if self._current_asset else[]
        for i, l in enumerate(layers):
            if l.id == layer_id: return layers, i, parent
            result = self._find_layer_parent_and_list(layer_id, l.children, l)
            if result: return result
        return None

    def _add_layer_from_image(self):
        if not self.project: return
        if not self._current_asset:
            QMessageBox.information(self, "No Animation", "Create animation asset first using the '+ New' button above.")
            return

        img = None
        if self.project.images:
            choices =[f"{i.name}" for i in self.project.images] + ["— Browse for new image…"]
            choice, ok = QInputDialog.getItem(self, "Add Layer", "Select image:", choices, len(choices) - 1, False)
            if not ok: return
            if choice == "— Browse for new image…":
                img = self._browse_and_register_image()
            else:
                idx = choices.index(choice)
                img = self.project.images[idx]
        else:
            img = self._browse_and_register_image()

        if not img: return

        layer = PaperDollLayer(name=img.name, image_id=img.id)
        if img.path and os.path.isfile(img.path):
            pix = QPixmap(img.path)
            if not pix.isNull():
                layer.origin_x = pix.width() / 2.0
                layer.origin_y = pix.height() / 2.0

        if self._selected_layer:
            self._selected_layer.children.append(layer)
        else:
            self._current_asset.root_layers.append(layer)

        self._selected_layer = layer
        self._refresh_tree()
        self._refresh_properties()
        self._refresh_canvas()
        self._mark_changed()

    def _browse_and_register_image(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select Image(s)", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not paths: return None
        first_img = None
        for path in paths:
            name = os.path.splitext(os.path.basename(path))[0]
            img = RegisteredImage(name=name, path=path, category="character")
            self.project.images.append(img)
            if first_img is None: first_img = img
            if first_img is not img and self._current_asset:
                extra_layer = PaperDollLayer(name=img.name, image_id=img.id)
                if img.path and os.path.isfile(img.path):
                    pix = QPixmap(img.path)
                    if not pix.isNull():
                        extra_layer.origin_x = pix.width() / 2.0
                        extra_layer.origin_y = pix.height() / 2.0
                if self._selected_layer:
                    self._selected_layer.children.append(extra_layer)
                else:
                    self._current_asset.root_layers.append(extra_layer)
        return first_img

    def _delete_layer(self):
        if not self._selected_layer or not self._current_asset: return
        result = self._find_layer_parent_and_list(self._selected_layer.id)
        if not result: return
        parent_list, idx, _ = result
        parent_list.pop(idx)
        self._selected_layer = None
        self.canvas.set_selected_layer(None)
        self._refresh_tree()
        self._refresh_canvas()
        self._mark_changed()

    def _move_layer_up(self):
        if not self._selected_layer or not self._current_asset: return
        result = self._find_layer_parent_and_list(self._selected_layer.id)
        if not result: return
        parent_list, idx, _ = result
        if idx > 0:
            parent_list[idx], parent_list[idx - 1] = parent_list[idx - 1], parent_list[idx]
            self._refresh_tree()
            self._refresh_canvas()
            self._mark_changed()

    def _move_layer_down(self):
        if not self._selected_layer or not self._current_asset: return
        result = self._find_layer_parent_and_list(self._selected_layer.id)
        if not result: return
        parent_list, idx, _ = result
        if idx < len(parent_list) - 1:
            parent_list[idx], parent_list[idx + 1] = parent_list[idx + 1], parent_list[idx]
            self._refresh_tree()
            self._refresh_canvas()
            self._mark_changed()

    def _unparent_layer(self):
        if not self._selected_layer or not self._current_asset: return
        result = self._find_layer_parent_and_list(self._selected_layer.id)
        if not result: return
        parent_list, idx, parent_layer = result
        if parent_layer is None: return
        layer = parent_list.pop(idx)
        gp_result = self._find_layer_parent_and_list(parent_layer.id)
        if gp_result:
            gp_list, gp_idx, _ = gp_result
            gp_list.insert(gp_idx + 1, layer)
        else:
            self._current_asset.root_layers.append(layer)
        self._refresh_tree()
        self._refresh_canvas()
        self._mark_changed()

    def _reparent_layer(self):
        if not self._selected_layer or not self._current_asset: return
        result = self._find_layer_parent_and_list(self._selected_layer.id)
        if not result: return
        parent_list, idx, _ = result
        if idx == 0: return
        layer = parent_list.pop(idx)
        new_parent = parent_list[idx - 1]
        new_parent.children.append(layer)
        self._refresh_tree()
        self._refresh_canvas()
        self._mark_changed()

    # ── Properties panel ───────────────────────────────────────

    def _refresh_properties(self):
        self._suppress_signals = True
        layer = self._selected_layer
        has_layer = layer is not None

        self.layer_name_edit.setEnabled(has_layer)
        for spin in self.prop_spins.values(): spin.setEnabled(has_layer)
        self.origin_x_spin.setEnabled(has_layer)
        self.origin_y_spin.setEnabled(has_layer)

        if layer:
            self.layer_name_edit.setText(layer.name)
            self.prop_spins["X Offset"].setValue(layer.x)
            self.prop_spins["Y Offset"].setValue(layer.y)
            self.prop_spins["Rotation"].setValue(layer.rotation)
            self.prop_spins["Scale X"].setValue(layer.scale_x)
            self.prop_spins["Scale Y"].setValue(layer.scale_y)
            self.origin_x_spin.setValue(layer.origin_x)
            self.origin_y_spin.setValue(layer.origin_y)
            # Mesh deform UI
            self.mesh_enable_cb.setChecked(layer.mesh_deform.enabled)
            self.mesh_cols_spin.setValue(layer.mesh_deform.grid_cols)
            self.mesh_rows_spin.setValue(layer.mesh_deform.grid_rows)
            self.mesh_enable_cb.setEnabled(True)
            self.mesh_cols_spin.setEnabled(layer.mesh_deform.enabled)
            self.mesh_rows_spin.setEnabled(layer.mesh_deform.enabled)
            self.mesh_kf_diamond.setEnabled(layer.mesh_deform.enabled)
            self.btn_mesh_reset.setEnabled(layer.mesh_deform.enabled)
        else:
            self.layer_name_edit.clear()
            for spin in self.prop_spins.values(): spin.setValue(0.0)
            self.origin_x_spin.setValue(0.0)
            self.origin_y_spin.setValue(0.0)
            self.mesh_enable_cb.setChecked(False)
            self.mesh_enable_cb.setEnabled(False)
            self.mesh_cols_spin.setEnabled(False)
            self.mesh_rows_spin.setEnabled(False)
            self.mesh_kf_diamond.setEnabled(False)
            self.btn_mesh_reset.setEnabled(False)
            self._selected_mesh_cell = None

        # Refresh cell inspector
        self._refresh_mesh_cell_inspector()

        self._suppress_signals = False

    def _refresh_mesh_cell_inspector(self):
        """Populate the 8 cell-corner spinboxes from the current mesh offsets."""
        layer = self._selected_layer
        cell = self._selected_mesh_cell
        mesh_ok = bool(layer and layer.mesh_deform.enabled and cell is not None)

        for corner in ("TL", "TR", "BL", "BR"):
            sx, sy = self.mesh_corner_spins[corner]
            sx.setEnabled(mesh_ok)
            sy.setEnabled(mesh_ok)
            self.mesh_corner_diamonds[corner].setEnabled(mesh_ok)

        if not mesh_ok:
            self.mesh_cell_label.setText("No cell selected")
            for corner in ("TL", "TR", "BL", "BR"):
                sx, sy = self.mesh_corner_spins[corner]
                sx.setValue(0.0)
                sy.setValue(0.0)
            return

        r, c = cell
        cfg = layer.mesh_deform
        cols = cfg.grid_cols
        self.mesh_cell_label.setText(f"Cell ({r}, {c})")

        offsets = self.canvas.get_mesh_offsets(layer.id)
        vert_indices = {
            "TL": r * (cols + 1) + c,
            "TR": r * (cols + 1) + c + 1,
            "BL": (r + 1) * (cols + 1) + c,
            "BR": (r + 1) * (cols + 1) + c + 1,
        }
        for corner, vi in vert_indices.items():
            sx, sy = self.mesh_corner_spins[corner]
            if vi < len(offsets):
                sx.setValue(offsets[vi][0])
                sy.setValue(offsets[vi][1])
            else:
                sx.setValue(0.0)
                sy.setValue(0.0)

    def _on_layer_name_changed(self):
        if self._suppress_signals or not self._selected_layer: return
        self._selected_layer.name = self.layer_name_edit.text()
        item = self.tree.currentItem()
        if item: item.setText(0, self._selected_layer.name)
        self._mark_changed()

    def _on_property_spin_changed(self, value):
        if self._suppress_signals or not self._selected_layer: return
        sender = self.sender()
        prop_name = sender.property("prop_name")
        if prop_name == "X Offset": self._selected_layer.x = value
        elif prop_name == "Y Offset": self._selected_layer.y = value
        elif prop_name == "Rotation": self._selected_layer.rotation = value
        elif prop_name == "Scale X": self._selected_layer.scale_x = value
        elif prop_name == "Scale Y": self._selected_layer.scale_y = value
        self._refresh_canvas(update_only=True)
        self._mark_changed()

    def _on_origin_changed(self, _value):
        if self._suppress_signals or not self._selected_layer: return
        self._selected_layer.origin_x = self.origin_x_spin.value()
        self._selected_layer.origin_y = self.origin_y_spin.value()
        self._refresh_canvas(update_only=True)
        self._mark_changed()

    # ── Canvas interaction ─────────────────────────────────────

    def _on_canvas_layer_moved(self, layer_id: str, dx: float, dy: float):
        if not self._current_asset: return
        layer = self._current_asset.find_layer(layer_id)
        if not layer: return
        layer.x += dx
        layer.y += dy
        self._selected_layer = layer
        self.canvas.set_selected_layer(layer_id)
        self._select_tree_item(layer_id)
        self._refresh_properties()
        self._refresh_canvas(update_only=True)
        self._mark_changed()

    def _on_canvas_origin_moved(self, layer_id: str, dx: float, dy: float):
        if not self._current_asset: return
        layer = self._current_asset.find_layer(layer_id)
        if not layer: return
        layer.origin_x += dx
        layer.origin_y += dy
        self._refresh_properties()
        self._refresh_canvas(update_only=True)
        self._mark_changed()

    def _on_canvas_layer_clicked(self, layer_id: str):
        if not self._current_asset: return
        layer = self._current_asset.find_layer(layer_id)
        if layer:
            self._selected_layer = layer
            self._select_tree_item(layer_id)
            self._refresh_properties()
            self.canvas.set_selected_layer(layer_id)

    # ── Mesh deform handlers ──────────────────────────────────

    def _ensure_mesh_offsets(self, layer: PaperDollLayer):
        """Ensure the canvas has a valid offset array for this mesh layer."""
        cfg = layer.mesh_deform
        expected = (cfg.grid_cols + 1) * (cfg.grid_rows + 1)
        offsets = self.canvas.get_mesh_offsets(layer.id)
        if len(offsets) != expected:
            self.canvas.set_mesh_offsets(layer.id, [[0.0, 0.0] for _ in range(expected)])

    def _on_mesh_enable_toggled(self, checked):
        if self._suppress_signals or not self._selected_layer: return
        self._selected_layer.mesh_deform.enabled = checked
        if checked:
            self._ensure_mesh_offsets(self._selected_layer)
        else:
            # Clear offsets when disabling
            self.canvas.set_mesh_offsets(self._selected_layer.id, [])
        self._refresh_properties()
        self._refresh_canvas()
        self._mark_changed()

    def _on_mesh_grid_changed(self, _value):
        if self._suppress_signals or not self._selected_layer: return
        self._selected_layer.mesh_deform.grid_cols = int(self.mesh_cols_spin.value())
        self._selected_layer.mesh_deform.grid_rows = int(self.mesh_rows_spin.value())
        # Reset offsets when grid size changes
        self._ensure_mesh_offsets(self._selected_layer)
        # Also clear any stored offsets since vert count changed
        cfg = self._selected_layer.mesh_deform
        expected = (cfg.grid_cols + 1) * (cfg.grid_rows + 1)
        self.canvas.set_mesh_offsets(self._selected_layer.id, [[0.0, 0.0] for _ in range(expected)])
        self._refresh_canvas()
        self._mark_changed()

    def _on_mesh_reset(self):
        if not self._selected_layer or not self._selected_layer.mesh_deform.enabled: return
        cfg = self._selected_layer.mesh_deform
        expected = (cfg.grid_cols + 1) * (cfg.grid_rows + 1)
        self.canvas.set_mesh_offsets(self._selected_layer.id, [[0.0, 0.0] for _ in range(expected)])
        self._refresh_canvas()
        self._mark_changed()

    def _on_canvas_mesh_vert_moved(self, layer_id: str, vert_index: int, dx: float, dy: float):
        """Handle dragging a mesh vertex on the canvas."""
        if not self._current_asset: return
        layer = self._current_asset.find_layer(layer_id)
        if not layer or not layer.mesh_deform.enabled: return
        offsets = self.canvas.get_mesh_offsets(layer_id)
        if vert_index >= len(offsets): return

        composed = self.canvas._get_layer_composed_transform(layer)
        if composed is None: return
        inv, ok = composed.inverted()
        if not ok: return

        origin_local = inv.map(QPointF(0, 0))
        delta_local = inv.map(QPointF(dx, dy))
        local_dx = delta_local.x() - origin_local.x()
        local_dy = delta_local.y() - origin_local.y()

        offsets[vert_index][0] += local_dx
        offsets[vert_index][1] += local_dy
        self.canvas.set_mesh_offsets(layer_id, offsets)
        # Only rebuild the canvas visuals — do NOT call _refresh_properties
        # which would re-read layer transforms and could cause feedback loops
        self.canvas.rebuild(self._current_asset, self.project,
                            image_swaps=self._preview_image_swaps,
                            scale_offsets=self._preview_scale_offsets)
        self.canvas.set_selected_layer(self._selected_layer.id if self._selected_layer else None)
        # Sync cell inspector spinboxes only
        self._suppress_signals = True
        self._refresh_mesh_cell_inspector()
        self._suppress_signals = False
        self._mark_changed()

    def _on_mesh_cell_clicked(self, row: int, col: int):
        """Handle clicking a mesh cell on the canvas."""
        if row == -1 or col == -1:
            self._selected_mesh_cell = None
        else:
            self._selected_mesh_cell = (row, col)
        self._suppress_signals = True
        self._refresh_mesh_cell_inspector()
        self._suppress_signals = False

    def _on_mesh_corner_spin_changed(self, value):
        """Handle editing a mesh cell corner spinbox — update the canvas offset."""
        if self._suppress_signals: return
        if not self._selected_layer or not self._selected_layer.mesh_deform.enabled: return
        if self._selected_mesh_cell is None: return

        sender = self.sender()
        corner = sender.property("mesh_corner")
        axis = sender.property("mesh_axis")
        r, c = self._selected_mesh_cell
        cfg = self._selected_layer.mesh_deform
        cols = cfg.grid_cols

        vert_indices = {
            "TL": r * (cols + 1) + c,
            "TR": r * (cols + 1) + c + 1,
            "BL": (r + 1) * (cols + 1) + c,
            "BR": (r + 1) * (cols + 1) + c + 1,
        }
        vi = vert_indices.get(corner)
        if vi is None: return

        offsets = self.canvas.get_mesh_offsets(self._selected_layer.id)
        if vi >= len(offsets): return

        if axis == "x":
            offsets[vi][0] = value
        else:
            offsets[vi][1] = value
        self.canvas.set_mesh_offsets(self._selected_layer.id, offsets)
        self._refresh_canvas()
        self._mark_changed()

    def _on_mesh_cell_keyframe_diamond_clicked(self):
        """Snapshot all 4 corner offsets for the selected cell at the current time.
        This is equivalent to hitting 'Snapshot All Verts' but scoped to the cell."""
        # For now, a per-cell keyframe still snapshots the whole mesh
        # (since mesh keyframes store all verts). This just provides a convenient
        # button near the cell controls.
        self._on_mesh_keyframe_diamond_clicked()

    def _on_mesh_keyframe_diamond_clicked(self):
        """Snapshot all mesh vert offsets for the selected layer at the current time."""
        if not self._current_macro or not self._selected_layer: return
        if not self._selected_layer.mesh_deform.enabled: return

        time = self._playback_time
        lid = self._selected_layer.id
        offsets = self.canvas.get_mesh_offsets(lid)
        if not offsets: return

        # Deep copy the offsets
        snapshot = [list(o) for o in offsets]

        # Check if a mesh keyframe already exists at this time for this layer
        existing = [mk for mk in self._current_macro.mesh_keyframes
                    if mk.layer_id == lid and abs(mk.time - time) < 0.01]

        if existing:
            existing[0].offsets = snapshot
        else:
            mk = MeshKeyframe(time=round(time, 3), layer_id=lid, offsets=snapshot)
            self._current_macro.mesh_keyframes.append(mk)
            self._current_macro.mesh_keyframes.sort(key=lambda k: k.time)

        self.timeline.update_keyframes(self._current_macro)
        self._mark_changed()

    # ── Behavior config ────────────────────────────────────────

    def _open_behavior_dialog(self, mode: str):
        if not self._current_asset or not self.project:
            QMessageBox.information(self, "No Asset", "Create or select an animation asset first.")
            return
        dlg = BehaviorConfigDialog(self._current_asset, mode, self.project, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.apply()
            self._mark_changed()

    # ── Behavior preview ───────────────────────────────────────

    def _any_preview_active(self):
        return self._preview_idle or self._preview_blink

    def _ensure_preview_timer(self):
        if self._any_preview_active():
            if not self._preview_timer.isActive():
                self._preview_time = 0.0
                self._preview_timer.start()
        else:
            self._preview_timer.stop()
            self._preview_image_swaps.clear()
            self._preview_scale_offsets.clear()
            self._refresh_canvas()

    def _toggle_preview_idle(self, checked: bool):
        self._preview_idle = checked
        if not checked:
            self._preview_scale_offsets.clear()
            self._refresh_canvas()
        self._ensure_preview_timer()

    def _toggle_preview_blink(self, checked: bool):
        self._preview_blink = checked
        if checked:
            self._blink_active = False
            self._blink_next = self._preview_time + 1.0
        else:
            if self._current_asset and self._current_asset.blink.layer_id:
                self._preview_image_swaps.pop(self._current_asset.blink.layer_id, None)
            self._refresh_canvas()
        self._ensure_preview_timer()

    def _tick_preview(self):
        if not self._current_asset: return
        dt = 0.016
        self._preview_time += dt
        self._compute_behaviors()
        self._refresh_canvas_preview()

    def _compute_behaviors(self):
        """Compute blink and idle breathing state from self._preview_time.
        Populates self._preview_image_swaps and self._preview_scale_offsets.
        Safe to call from preview timer, playback timer, or export loop."""
        if not self._current_asset:
            return

        # Idle breathing
        cfg_idle = self._current_asset.idle_breathing
        if cfg_idle.enabled and cfg_idle.speed > 0:
            phase = (self._preview_time / cfg_idle.speed) * math.pi * 2
            offset = math.sin(phase) * cfg_idle.scale_amount
            offset_tuple = (offset, offset)
            target_id = cfg_idle.layer_id if cfg_idle.layer_id else None
            if target_id:
                self._preview_scale_offsets = {target_id: offset_tuple}
            else:
                self._preview_scale_offsets = {l.id: offset_tuple for l in self._current_asset.root_layers}
        else:
            self._preview_scale_offsets.clear()

        # Blink
        cfg_blink = self._current_asset.blink
        if cfg_blink.enabled and cfg_blink.layer_id and cfg_blink.alt_image_id:
            if self._blink_active:
                if self._preview_time >= self._blink_end:
                    self._blink_active = False
                    self._preview_image_swaps.pop(cfg_blink.layer_id, None)
                    interval = random.uniform(cfg_blink.interval_min, cfg_blink.interval_max)
                    self._blink_next = self._preview_time + interval
            else:
                if self._preview_time >= self._blink_next:
                    self._blink_active = True
                    self._blink_end = self._preview_time + cfg_blink.blink_duration
                    self._preview_image_swaps[cfg_blink.layer_id] = cfg_blink.alt_image_id

    # ── Macro management ───────────────────────────────────────

    def _refresh_macro_list(self):
        self.macro_list.blockSignals(True)
        self.macro_list.clear()
        if self._current_asset:
            for m in self._current_asset.macros:
                item = QTreeWidgetItem(self.macro_list, [m.name])
                item.setData(0, Qt.ItemDataRole.UserRole, m.id)
        self.macro_list.blockSignals(False)

    def _on_macro_selection_changed(self, current, previous):
        if not current or not self._current_asset:
            self._current_macro = None
        else:
            mid = current.data(0, Qt.ItemDataRole.UserRole)
            self._current_macro = next((m for m in self._current_asset.macros if m.id == mid), None)

        self._suppress_signals = True
        if self._current_macro:
            self.macro_duration_spin.setEnabled(True)
            self.macro_loop_cb.setEnabled(True)
            self.macro_duration_spin.setValue(self._current_macro.duration)
            self.macro_loop_cb.setChecked(self._current_macro.loop)
        else:
            self.macro_duration_spin.setEnabled(False)
            self.macro_loop_cb.setEnabled(False)
        self._suppress_signals = False

        self.timeline.set_macro(self._current_macro)
        self._playback_time = 0.0

    def _new_macro(self):
        if not self._current_asset: return
        name, ok = QInputDialog.getText(self, "New Macro", "Macro name:")
        if not ok or not name.strip(): return
        macro = PaperDollMacro(name=name.strip())
        self._current_asset.macros.append(macro)
        self._refresh_macro_list()
        for i in range(self.macro_list.topLevelItemCount()):
            item = self.macro_list.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == macro.id:
                self.macro_list.setCurrentItem(item)
                break
        self._mark_changed()

    def _rename_macro(self):
        if not self._current_macro: return
        name, ok = QInputDialog.getText(self, "Rename Macro", "New name:", text=self._current_macro.name)
        if ok and name.strip():
            self._current_macro.name = name.strip()
            self._refresh_macro_list()
            self.timeline.set_macro(self._current_macro)
            self._mark_changed()

    def _delete_macro(self):
        if not self._current_macro or not self._current_asset: return
        self._current_asset.macros.remove(self._current_macro)
        self._current_macro = None
        self._refresh_macro_list()
        self.timeline.set_macro(None)
        self._mark_changed()

    def _on_macro_duration_changed(self, value):
        if self._suppress_signals or not self._current_macro: return
        self._current_macro.duration = value
        self.timeline.set_macro(self._current_macro)
        self._mark_changed()

    def _on_macro_loop_changed(self, checked):
        if self._suppress_signals or not self._current_macro: return
        self._current_macro.loop = checked
        self._mark_changed()

    # ── Keyframing ─────────────────────────────────────────────

    def _on_keyframe_diamond_clicked(self):
        if not self._current_macro or not self._selected_layer: return
        time = self._playback_time
        lid = self._selected_layer.id

        existing =[k for k in self._current_macro.keyframes if k.layer_id == lid and abs(k.time - time) < 0.01]

        if existing:
            kf = existing[0]
            kf.x = self._selected_layer.x
            kf.y = self._selected_layer.y
            kf.rotation = self._selected_layer.rotation
            kf.scale_x = self._selected_layer.scale_x
            kf.scale_y = self._selected_layer.scale_y
        else:
            kf = PaperDollKeyframe(
                time=round(time, 3), layer_id=lid,
                x=self._selected_layer.x, y=self._selected_layer.y,
                rotation=self._selected_layer.rotation,
                scale_x=self._selected_layer.scale_x, scale_y=self._selected_layer.scale_y,
            )
            self._current_macro.keyframes.append(kf)
            self._current_macro.keyframes.sort(key=lambda k: k.time)

        self.timeline.update_keyframes(self._current_macro)
        self._mark_changed()

    def _keyframe_prev(self):
        if not self._current_macro or not self._current_macro.keyframes: return
        times = sorted(set(k.time for k in self._current_macro.keyframes))
        prev_times =[t for t in times if t < self._playback_time - 0.01]
        self._playback_time = prev_times[-1] if prev_times else 0.0
        self._apply_macro_at_time(self._playback_time)
        self.timeline.set_time(self._playback_time, self._current_macro.duration)

    def _keyframe_next(self):
        if not self._current_macro or not self._current_macro.keyframes: return
        times = sorted(set(k.time for k in self._current_macro.keyframes))
        next_times =[t for t in times if t > self._playback_time + 0.01]
        self._playback_time = next_times[0] if next_times else self._current_macro.duration
        self._apply_macro_at_time(self._playback_time)
        self.timeline.set_time(self._playback_time, self._current_macro.duration)

    # ── Playback ───────────────────────────────────────────────

    def _on_play_toggled(self, playing: bool):
        if playing and self._current_macro:
            # Initialize behavior state for playback
            self._preview_time = self._playback_time
            if self._current_asset and self._current_asset.blink.enabled:
                self._blink_active = False
                interval = random.uniform(
                    self._current_asset.blink.interval_min,
                    self._current_asset.blink.interval_max
                )
                self._blink_next = self._preview_time + interval
            self._playback_timer.start()
        else:
            self._playback_timer.stop()
            # Clear behavior overlays when stopping
            self._preview_image_swaps.clear()
            self._preview_scale_offsets.clear()
            self._blink_active = False
            self._refresh_canvas()

    def _on_time_scrubbed(self, normalized: float):
        if not self._current_macro: return
        self._playback_time = normalized * self._current_macro.duration
        self._apply_macro_at_time(self._playback_time)
        self.timeline.set_time(self._playback_time, self._current_macro.duration)

    def _tick_playback(self):
        if not self._current_macro:
            self._playback_timer.stop()
            return
        dt = 0.016
        self._playback_time += dt
        if self._playback_time >= self._current_macro.duration:
            if self._current_macro.loop:
                self._playback_time = 0.0
            else:
                self._playback_time = self._current_macro.duration
                self._playback_timer.stop()
                self.timeline.btn_play.setChecked(False)

        # Simulate blink/idle behaviors during macro playback
        self._preview_time += dt
        self._compute_behaviors()

        self._apply_macro_at_time(self._playback_time)
        self.timeline.set_time(self._playback_time, self._current_macro.duration)

    # ── Exporting ──────────────────────────────────────────────
    
    def _export_macro_pngs(self):
        """Export the currently selected macro to a folder of PNGs."""
        if not self._current_macro or not self._current_asset:
            QMessageBox.information(self, "No Macro", "Select a macro to export.")
            return

        folder = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if not folder: return

        fps, ok = QInputDialog.getInt(self, "Export FPS", "Frames per second:", 60, 1, 120)
        if not ok: return

        duration = self._current_macro.duration
        total_frames = int(duration * fps)
        if total_frames <= 0: return

        # Save current playback state
        original_time = self._playback_time
        was_playing = self._playback_timer.isActive()
        if was_playing: self._playback_timer.stop()

        # Save preview state
        original_preview_time = self._preview_time
        original_blink_active = self._blink_active
        original_blink_next = self._blink_next
        original_blink_end = self._blink_end
        original_image_swaps = dict(self._preview_image_swaps)
        original_scale_offsets = dict(self._preview_scale_offsets)

        # Temporarily hide origin marker and background for clean export
        original_layer = self._selected_layer
        self.canvas._exporting = True
        self.canvas.set_selected_layer(None)

        # Explicitly hide origin marker graphics items so they don't render
        origin_items = (self.canvas._origin_circle, self.canvas._origin_hline, self.canvas._origin_vline)
        for item in origin_items:
            if item and item.scene():
                item.setVisible(False)
        
        # We need a transparent background for the export
        original_bg = self.canvas.backgroundBrush()
        self.canvas.setBackgroundBrush(Qt.BrushStyle.NoBrush)

        # Reset behavior state for deterministic export
        self._preview_time = 0.0
        self._blink_active = False
        self._blink_next = random.uniform(
            self._current_asset.blink.interval_min,
            self._current_asset.blink.interval_max
        ) if self._current_asset.blink.enabled else 999.0
        self._preview_image_swaps.clear()
        self._preview_scale_offsets.clear()

        # First pass: compute unified bounding rect across ALL frames
        scene = self.canvas.scene()
        unified_rect = QRectF()
        for i in range(total_frames + 1):
            t = i / fps
            if t > duration: t = duration
            self._preview_time = t
            self._compute_behaviors()
            self._apply_macro_at_time(t)
            QApplication.processEvents()
            frame_rect = scene.itemsBoundingRect()
            if not frame_rect.isEmpty():
                unified_rect = unified_rect.united(frame_rect)

        if unified_rect.isEmpty():
            unified_rect = QRectF(0, 0, 960, 544)
        else:
            unified_rect.adjust(-20, -20, 20, 20)

        out_w = int(unified_rect.width())
        out_h = int(unified_rect.height())

        # Reset behavior state for deterministic second pass
        self._preview_time = 0.0
        self._blink_active = False
        self._blink_next = random.uniform(
            self._current_asset.blink.interval_min,
            self._current_asset.blink.interval_max
        ) if self._current_asset.blink.enabled else 999.0
        self._preview_image_swaps.clear()
        self._preview_scale_offsets.clear()

        # Second pass: render each frame at the unified size
        for i in range(total_frames + 1):
            t = i / fps
            if t > duration: t = duration
            
            self._preview_time = t
            self._compute_behaviors()
            self._apply_macro_at_time(t)
            QApplication.processEvents()

            image = QImage(out_w, out_h, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            scene.render(painter, target=QRectF(image.rect()), source=unified_rect)
            painter.end()

            filename = os.path.join(folder, f"{self._current_macro.name}_{i:04d}.png")
            image.save(filename)

        # Restore state
        self.canvas._exporting = False
        self.canvas.setBackgroundBrush(original_bg)
        self.canvas.set_selected_layer(original_layer.id if original_layer else None)
        self._playback_time = original_time
        self._preview_time = original_preview_time
        self._blink_active = original_blink_active
        self._blink_next = original_blink_next
        self._blink_end = original_blink_end
        self._preview_image_swaps = original_image_swaps
        self._preview_scale_offsets = original_scale_offsets
        self._apply_macro_at_time(self._playback_time)
        if was_playing: self._playback_timer.start()

        QMessageBox.information(self, "Export Complete", f"Successfully exported {total_frames + 1} frames to:\n{folder}")


    # ── Refresh helpers ────────────────────────────────────────

    def _refresh_all(self):
        self._refresh_tree()
        self._refresh_properties()
        self._refresh_macro_list()
        self._refresh_canvas()
        self.timeline.set_macro(self._current_macro)

    def _refresh_canvas(self, update_only=False):
        has_behavior_state = bool(self._preview_image_swaps or self._preview_scale_offsets)
        if update_only:
            self.canvas.update_transforms(self._current_asset, self.project,
                                          image_swaps=self._preview_image_swaps,
                                          scale_offsets=self._preview_scale_offsets)
        else:
            if self._any_preview_active() or has_behavior_state:
                self.canvas.rebuild(self._current_asset, self.project,
                                    image_swaps=self._preview_image_swaps,
                                    scale_offsets=self._preview_scale_offsets)
            else:
                self.canvas.rebuild(self._current_asset, self.project)
        self.canvas.set_selected_layer(self._selected_layer.id if self._selected_layer else None)

    def _refresh_canvas_preview(self):
        """Lightweight refresh during preview animation — utilizes fast updates."""
        self.canvas.update_transforms(self._current_asset, self.project,
                            image_swaps=self._preview_image_swaps,
                            scale_offsets=self._preview_scale_offsets)
        self.canvas.set_selected_layer(self._selected_layer.id if self._selected_layer else None)

    def _apply_macro_at_time(self, t: float):
        if not self._current_macro or not self._current_asset: return

        has_mesh_keyframes = False

        by_layer = {}
        for kf in self._current_macro.keyframes:
            if kf.layer_id not in by_layer:
                by_layer[kf.layer_id] = []
            by_layer[kf.layer_id].append(kf)

        for lid, kfs in by_layer.items():
            layer = self._current_asset.find_layer(lid)
            if not layer: continue
            kfs_sorted = sorted(kfs, key=lambda k: k.time)
            
            before = None
            after = None
            for kf in kfs_sorted:
                if kf.time <= t: before = kf
                if kf.time >= t and after is None: after = kf

            if before and after and before is not after:
                span = after.time - before.time
                frac = (t - before.time) / span if span > 0 else 0.0
                layer.x = before.x + (after.x - before.x) * frac
                layer.y = before.y + (after.y - before.y) * frac
                layer.rotation = before.rotation + (after.rotation - before.rotation) * frac
                layer.scale_x = before.scale_x + (after.scale_x - before.scale_x) * frac
                layer.scale_y = before.scale_y + (after.scale_y - before.scale_y) * frac
            elif before:
                layer.x = before.x
                layer.y = before.y
                layer.rotation = before.rotation
                layer.scale_x = before.scale_x
                layer.scale_y = before.scale_y
            elif after:
                layer.x = after.x
                layer.y = after.y
                layer.rotation = after.rotation
                layer.scale_x = after.scale_x
                layer.scale_y = after.scale_y

        # Mesh keyframe interpolation
        mesh_by_layer = {}
        for mk in self._current_macro.mesh_keyframes:
            if mk.layer_id not in mesh_by_layer:
                mesh_by_layer[mk.layer_id] = []
            mesh_by_layer[mk.layer_id].append(mk)

        for lid, mks in mesh_by_layer.items():
            layer = self._current_asset.find_layer(lid)
            if not layer or not layer.mesh_deform.enabled: continue
            has_mesh_keyframes = True
            mks_sorted = sorted(mks, key=lambda k: k.time)

            before = None
            after = None
            for mk in mks_sorted:
                if mk.time <= t: before = mk
                if mk.time >= t and after is None: after = mk

            if before and after and before is not after:
                span = after.time - before.time
                frac = (t - before.time) / span if span > 0 else 0.0
                # Lerp each vertex offset
                lerped = []
                for i in range(len(before.offsets)):
                    if i < len(after.offsets):
                        dx = before.offsets[i][0] + (after.offsets[i][0] - before.offsets[i][0]) * frac
                        dy = before.offsets[i][1] + (after.offsets[i][1] - before.offsets[i][1]) * frac
                        lerped.append([dx, dy])
                    else:
                        lerped.append(list(before.offsets[i]))
                self.canvas.set_mesh_offsets(lid, lerped)
            elif before:
                self.canvas.set_mesh_offsets(lid, [list(o) for o in before.offsets])
            elif after:
                self.canvas.set_mesh_offsets(lid, [list(o) for o in after.offsets])

        self._refresh_properties()
        # Mesh layers need full rebuild since textured quads must be recreated
        if has_mesh_keyframes:
            self._refresh_canvas()
        else:
            self._refresh_canvas(update_only=True)

    def _mark_changed(self):
        self.changed.emit()


# ── Standalone Execution ────────────────────────────────────────
if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    
    # Initialize a blank project for standalone mode
    project = Project.new()
    
    tab = PaperDollTab()
    tab.setWindowTitle("FreeBones — Standalone Animation Editor")
    tab.resize(1280, 850)
    tab.setStyleSheet(f"background: {DARK}; color: {TEXT};")
    
    # Load the blank project into the UI
    tab.load_project(project)
    tab.show()
    
    sys.exit(app.exec())