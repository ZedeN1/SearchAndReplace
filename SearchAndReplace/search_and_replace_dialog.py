import re
from qgis.PyQt.QtWidgets import (QApplication, QDialog, QDockWidget, QWidget,
                                 QVBoxLayout, QHBoxLayout, QLabel,
                                 QPushButton, QListWidget, QListWidgetItem,
                                 QAbstractItemView, QCheckBox, QMessageBox,
                                 QTableWidget, QTableWidgetItem, QHeaderView,
                                 QTextBrowser)
from qgis.PyQt.QtCore import Qt
from qgis.core import QgsProject, QgsVectorLayer, QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox


class _CopyableTable(QTableWidget):
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_C and event.modifiers() & Qt.ControlModifier:
            indexes = self.selectedIndexes()
            if not indexes:
                return
            rows = sorted({i.row() for i in indexes})
            cols = sorted({i.column() for i in indexes})
            lines = []
            for r in rows:
                cells = []
                for c in cols:
                    item = self.item(r, c)
                    cells.append(item.text() if item else "")
                lines.append("\t".join(cells))
            QApplication.clipboard().setText("\n".join(lines))
        else:
            super().keyPressEvent(event)


class _PairsTable(_CopyableTable):
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_V and event.modifiers() & Qt.ControlModifier:
            text = QApplication.clipboard().text()
            if not text:
                return
            rows = text.replace("\r\n", "\n").rstrip("\n").split("\n")
            indexes = self.selectedIndexes()
            start_row = min(i.row() for i in indexes) if indexes else 0
            start_col = min(i.column() for i in indexes) if indexes else 0
            for r, row_text in enumerate(rows):
                target_row = start_row + r
                while target_row >= self.rowCount():
                    self.insertRow(self.rowCount())
                for c, cell in enumerate(row_text.split("\t")):
                    target_col = start_col + c
                    if target_col < self.columnCount():
                        self.setItem(target_row, target_col, QTableWidgetItem(cell))
        else:
            super().keyPressEvent(event)


class _LayerPickerDialog(QDialog):
    def __init__(self, selected_ids, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Layers")
        self.resize(300, 350)
        v = QVBoxLayout(self)

        self._list = QListWidget()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                item = QListWidgetItem(layer.name())
                item.setData(Qt.UserRole, layer.id())
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if layer.id() in selected_ids else Qt.Unchecked)
                self._list.addItem(item)
        v.addWidget(self._list)

        btns = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        v.addLayout(btns)

    def selected_ids(self):
        return [
            self._list.item(i).data(Qt.UserRole)
            for i in range(self._list.count())
            if self._list.item(i).checkState() == Qt.Checked
        ]


class SearchAndReplacePanel(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("Search and Replace", parent)
        self.iface = iface
        self.setObjectName("SearchAndReplacePanel")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)

        container = QWidget()
        self.setWidget(container)
        layout = QVBoxLayout(container)

        # --- Layer selector row ---
        layout.addWidget(QLabel("Input Layer(s):"))
        layer_row = QHBoxLayout()

        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setFilters(QgsMapLayerProxyModel.VectorLayer)
        self.layer_combo.layerChanged.connect(self._on_single_layer_changed)
        layer_row.addWidget(self.layer_combo)

        self.multi_layer_label = QLabel()
        self.multi_layer_label.hide()
        layer_row.addWidget(self.multi_layer_label)

        pick_btn = QPushButton("...")
        pick_btn.setFixedWidth(28)
        pick_btn.setToolTip("Select multiple layers")
        pick_btn.clicked.connect(self._open_layer_picker)
        layer_row.addWidget(pick_btn)

        layout.addLayout(layer_row)

        # --- Fields table ---
        layout.addWidget(QLabel("Select Fields:"))
        self.fields_table = QTableWidget(0, 2)
        self.fields_table.setHorizontalHeaderLabels(["Layer", "Field"])
        self.fields_table.setSortingEnabled(True)
        self.fields_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.fields_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.fields_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        hdr = self.fields_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        self.fields_table.setColumnHidden(0, True)  # hidden in single-layer mode
        layout.addWidget(self.fields_table)

        sel_btns = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self.fields_table.selectAll)
        deselect_btn = QPushButton("Deselect All")
        deselect_btn.clicked.connect(self.fields_table.clearSelection)
        sel_btns.addWidget(select_all_btn)
        sel_btns.addWidget(deselect_btn)
        sel_btns.addStretch()
        layout.addLayout(sel_btns)

        # --- Search/replace pairs ---
        layout.addWidget(QLabel("Search / Replace pairs:"))
        self.pairs_table = _PairsTable(1, 2)
        self.pairs_table.setHorizontalHeaderLabels(["Search for", "Replace with"])
        self.pairs_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.pairs_table.setMaximumHeight(200)
        layout.addWidget(self.pairs_table)

        pairs_btns = QHBoxLayout()
        add_btn = QPushButton("+ Add pair")
        add_btn.clicked.connect(self._add_pair_row)
        remove_btn = QPushButton("− Remove selected")
        remove_btn.clicked.connect(self._remove_pair_row)
        pairs_btns.addWidget(add_btn)
        pairs_btns.addWidget(remove_btn)
        pairs_btns.addStretch()
        layout.addLayout(pairs_btns)

        # --- Options ---
        regex_row = QHBoxLayout()
        self.regex_cb = QCheckBox("Use Regular Expressions (Regex)")
        regex_row.addWidget(self.regex_cb)
        help_btn = QPushButton("?")
        help_btn.setFixedWidth(28)
        help_btn.setToolTip("Show regex examples")
        help_btn.clicked.connect(self.show_regex_help)
        regex_row.addWidget(help_btn)
        layout.addLayout(regex_row)

        self.case_cb = QCheckBox("Case Insensitive")
        self.case_cb.setToolTip("In regex mode, use (?i) inline instead")
        self.regex_cb.toggled.connect(lambda on: self.case_cb.setEnabled(not on))
        layout.addWidget(self.case_cb)

        # --- Actions ---
        action_row = QHBoxLayout()
        preview_btn = QPushButton("Preview")
        preview_btn.clicked.connect(self.preview_replace)
        action_row.addWidget(preview_btn)
        run_btn = QPushButton("Replace All")
        run_btn.clicked.connect(self.execute_replace)
        action_row.addWidget(run_btn)
        layout.addLayout(action_row)

        # Seed initial selection from the combo's current layer
        self._selected_layer_ids = []
        self._on_single_layer_changed(self.layer_combo.currentLayer())

    def cleanup(self):
        pass  # no persistent signal connections to clean up

    # ------------------------------------------------------------------
    # Layer selection
    # ------------------------------------------------------------------

    def _on_single_layer_changed(self, layer):
        self._selected_layer_ids = [layer.id()] if layer else []
        self._update_fields_table()

    def _open_layer_picker(self):
        dlg = _LayerPickerDialog(self._selected_layer_ids, self)
        if dlg.exec_() != QDialog.Accepted:
            return
        ids = dlg.selected_ids()
        self._selected_layer_ids = ids
        self._apply_layer_selection()

    def _apply_layer_selection(self):
        n = len(self._selected_layer_ids)
        if n == 1:
            layer = QgsProject.instance().mapLayer(self._selected_layer_ids[0])
            self.layer_combo.blockSignals(True)
            self.layer_combo.setLayer(layer)
            self.layer_combo.blockSignals(False)
            self.layer_combo.show()
            self.multi_layer_label.hide()
            self.fields_table.setColumnHidden(0, True)
        elif n > 1:
            self.layer_combo.hide()
            self.multi_layer_label.setText(f"{n} layers selected")
            self.multi_layer_label.show()
            self.fields_table.setColumnHidden(0, False)
        else:
            self.layer_combo.show()
            self.multi_layer_label.hide()
            self.fields_table.setColumnHidden(0, True)
        self._update_fields_table()

    def _update_fields_table(self):
        self.fields_table.setSortingEnabled(False)
        self.fields_table.clearContents()
        self.fields_table.setRowCount(0)

        for lid in self._selected_layer_ids:
            layer = QgsProject.instance().mapLayer(lid)
            if not isinstance(layer, QgsVectorLayer):
                continue
            for field in layer.fields():
                row = self.fields_table.rowCount()
                self.fields_table.insertRow(row)
                layer_cell = QTableWidgetItem(layer.name())
                layer_cell.setData(Qt.UserRole, layer.id())
                self.fields_table.setItem(row, 0, layer_cell)
                self.fields_table.setItem(row, 1, QTableWidgetItem(field.name()))

        self.fields_table.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # Pairs table
    # ------------------------------------------------------------------

    def _add_pair_row(self):
        self.pairs_table.insertRow(self.pairs_table.rowCount())

    def _remove_pair_row(self):
        selected = sorted(
            {idx.row() for idx in self.pairs_table.selectedIndexes()},
            reverse=True
        )
        for row in selected:
            if self.pairs_table.rowCount() > 1:
                self.pairs_table.removeRow(row)

    def _get_pairs(self):
        pairs = []
        for row in range(self.pairs_table.rowCount()):
            s_item = self.pairs_table.item(row, 0)
            r_item = self.pairs_table.item(row, 1)
            search = s_item.text() if s_item else ""
            replace = r_item.text() if r_item else ""
            if search:
                pairs.append((search, replace))
        return pairs

    def _apply_pairs(self, val, pairs, use_regex, case_insensitive=False):
        new_val = val
        for search, replace in pairs:
            if use_regex:
                new_val = re.sub(search, replace, new_val)
            elif case_insensitive:
                new_val = re.sub(re.escape(search), replace, new_val, flags=re.IGNORECASE)
            else:
                new_val = new_val.replace(search, replace)
        return new_val

    def _validate(self):
        selected_rows = {idx.row() for idx in self.fields_table.selectedIndexes()}
        if not selected_rows:
            QMessageBox.warning(self, "Error", "Select at least one field.")
            return None, None

        layer_fields = {}  # layer_id -> [field_names]
        for row in selected_rows:
            layer_cell = self.fields_table.item(row, 0)
            field_cell = self.fields_table.item(row, 1)
            if layer_cell and field_cell:
                lid = layer_cell.data(Qt.UserRole)
                layer_fields.setdefault(lid, []).append(field_cell.text())

        layer_field_pairs = []
        for lid, fields in layer_fields.items():
            layer = QgsProject.instance().mapLayer(lid)
            if isinstance(layer, QgsVectorLayer):
                layer_field_pairs.append((layer, fields))

        if not layer_field_pairs:
            QMessageBox.warning(self, "Error", "No valid layers found.")
            return None, None

        pairs = self._get_pairs()
        if not pairs:
            QMessageBox.warning(self, "Error", "Enter at least one search term.")
            return None, None

        if self.regex_cb.isChecked():
            for search, _ in pairs:
                try:
                    re.compile(search)
                except re.error as e:
                    QMessageBox.critical(self, "Regex Error", f"Invalid pattern '{search}': {e}")
                    return None, None

        return layer_field_pairs, pairs

    # ------------------------------------------------------------------
    # Regex help
    # ------------------------------------------------------------------

    def show_regex_help(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Regex Help")
        dlg.resize(440, 480)
        v = QVBoxLayout(dlg)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)

        p = self.palette()
        code_bg = p.color(p.AlternateBase).name()
        border  = p.color(p.Mid).name()

        browser.setHtml(f"""
        <style>
            body  {{ font-family: sans-serif; font-size: 13px; margin: 4px; }}
            h3    {{ margin: 14px 0 4px 0; border-bottom: 1px solid {border}; padding-bottom: 2px; }}
            code  {{ font-family: 'Courier New', monospace; background: {code_bg};
                    padding: 1px 4px; border-radius: 3px; }}
            .row  {{ margin: 2px 0 2px 12px; }}
            .lbl  {{ display: inline-block; width: 60px; }}
        </style>

        <h3>Basics</h3>
        <table cellspacing="3" style="margin-left:12px">
          <tr><td><code>.</code></td>  <td>any single character</td></tr>
          <tr><td><code>.*</code></td> <td>zero or more of anything</td></tr>
          <tr><td><code>.+</code></td> <td>one or more of anything</td></tr>
          <tr><td><code>^text</code></td><td>starts with <code>text</code></td></tr>
          <tr><td><code>text$</code></td><td>ends with <code>text</code></td></tr>
          <tr><td><code>[abc]</code></td><td>any one of: a, b, c</td></tr>
          <tr><td><code>\\d</code></td>  <td>any digit (0–9)</td></tr>
          <tr><td><code>\\s</code></td>  <td>any whitespace</td></tr>
        </table>

        <h3>Capture Groups</h3>
        <p style="margin:6px 0 2px 0">Swap <code>Smith, John</code> &rarr; <code>John Smith</code></p>
        <div class="row"><span class="lbl">Search:</span>  <code>(\\w+), (\\w+)</code></div>
        <div class="row"><span class="lbl">Replace:</span> <code>\\2 \\1</code></div>

        <p style="margin:10px 0 2px 0">Reformat <code>2024-01-15</code> &rarr; <code>15/01/2024</code></p>
        <div class="row"><span class="lbl">Search:</span>  <code>(\\d{{4}})-(\\d{{2}})-(\\d{{2}})</code></div>
        <div class="row"><span class="lbl">Replace:</span> <code>\\3/\\2/\\1</code></div>

        <h3>Case-Insensitive</h3>
        <p style="margin:6px 0 2px 0">Match <code>Road</code>, <code>ROAD</code>, <code>road</code>, etc.</p>
        <div class="row"><span class="lbl">Search:</span>  <code>(?i)road</code></div>
        <div class="row"><span class="lbl">Replace:</span> <code>Rd</code></div>

        <h3>Strip Leading / Trailing Spaces</h3>
        <div class="row" style="margin-top:6px"><span class="lbl">Search:</span>  <code>^\\s+|\\s+$</code></div>
        <div class="row"><span class="lbl">Replace:</span> <i>(leave empty)</i></div>
        """)

        v.addWidget(browser)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        v.addWidget(close_btn)
        dlg.exec_()

    # ------------------------------------------------------------------
    # Preview / execute
    # ------------------------------------------------------------------

    def preview_replace(self):
        layer_field_pairs, pairs = self._validate()
        if layer_field_pairs is None:
            return

        use_regex = self.regex_cb.isChecked()
        case_insensitive = self.case_cb.isChecked()
        multi = len(self._selected_layer_ids) > 1
        preview_rows = []

        for layer, target_fields in layer_field_pairs:
            for feat in layer.getFeatures():
                for field_name in target_fields:
                    val = feat[field_name]
                    if isinstance(val, str) and val:
                        try:
                            new_val = self._apply_pairs(val, pairs, use_regex, case_insensitive)
                            if new_val != val:
                                preview_rows.append((layer.name(), field_name, feat.id(), val, new_val))
                        except re.error as e:
                            QMessageBox.critical(self, "Regex Error", f"Invalid regular expression: {e}")
                            return

        if not preview_rows:
            QMessageBox.information(self, "Preview", "No matches found.")
            return

        headers = (["Layer", "FID", "Field", "Original", "Replaced"] if multi
                   else ["FID", "Field", "Original", "Replaced"])
        col_count = len(headers)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Preview — {len(preview_rows)} change{'s' if len(preview_rows) != 1 else ''}")
        dlg.resize(900 if multi else 750, 420)
        v = QVBoxLayout(dlg)

        table = _CopyableTable(len(preview_rows), col_count)
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hdr = table.horizontalHeader()
        for c in range(col_count - 2):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(col_count - 2, QHeaderView.Stretch)
        hdr.setSectionResizeMode(col_count - 1, QHeaderView.Stretch)

        # Populate before enabling sort — inserting with sort on causes rows to shift mid-fill
        for i, (lyr, field, fid, orig, renamed) in enumerate(preview_rows):
            fid_item = QTableWidgetItem()
            fid_item.setData(Qt.DisplayRole, fid)  # int so it sorts numerically
            if multi:
                table.setItem(i, 0, QTableWidgetItem(lyr))
                table.setItem(i, 1, fid_item)
                table.setItem(i, 2, QTableWidgetItem(field))
                table.setItem(i, 3, QTableWidgetItem(orig))
                table.setItem(i, 4, QTableWidgetItem(renamed))
            else:
                table.setItem(i, 0, fid_item)
                table.setItem(i, 1, QTableWidgetItem(field))
                table.setItem(i, 2, QTableWidgetItem(orig))
                table.setItem(i, 3, QTableWidgetItem(renamed))

        table.setSortingEnabled(True)

        v.addWidget(table)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.accept)
        v.addWidget(close_btn)
        dlg.exec_()

    def execute_replace(self):
        layer_field_pairs, pairs = self._validate()
        if layer_field_pairs is None:
            return

        use_regex = self.regex_cb.isChecked()
        case_insensitive = self.case_cb.isChecked()

        total_count = 0
        summary = {}  # layer_name -> set of changed field names

        for layer, target_fields in layer_field_pairs:
            layer.startEditing()
            changed_fields = set()
            for feat in layer.getFeatures():
                for field_name in target_fields:
                    val = feat[field_name]
                    if isinstance(val, str) and val:
                        try:
                            new_val = self._apply_pairs(val, pairs, use_regex, case_insensitive)
                            if new_val != val:
                                idx = layer.fields().indexOf(field_name)
                                layer.changeAttributeValue(feat.id(), idx, new_val)
                                total_count += 1
                                changed_fields.add(field_name)
                        except re.error as e:
                            QMessageBox.critical(self, "Regex Error", f"Invalid regular expression: {e}")
                            return
            if changed_fields:
                summary[layer.name()] = changed_fields

        total_fields = sum(len(f) for f in summary.values())
        total_layers = len(summary)
        fw = "field" if total_fields == 1 else "fields"
        lw = "layer" if total_layers == 1 else "layers"
        ow = "occurrence" if total_count == 1 else "occurrences"
        QMessageBox.information(self, "Done",
            f"{total_count} {ow} replaced across {total_fields} {fw} in {total_layers} {lw}.")
