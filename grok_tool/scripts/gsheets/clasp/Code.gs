/**
 * GROK REG → Google Sheet tab "grok" ONLY
 *
 * Sổ tay CHUNG mọi acc reg + Sub2API thành công (không chỉ overnight).
 * - Chỉ 1 tab: grok
 * - Chỉ list FULL (thành công) — không list die/fail
 * - Mỗi lần export: ghi đè bảng FULL = toàn bộ success hiện có
 * - Xóa tab phụ Acc FULL / Acc FAIL / Lich su nếu còn
 *
 * Format:
 *   Title
 *   Cập nhật + Tổng FULL + Pass
 *   (optional) Batch gần nhất
 *   Table: # | Email | Password | Sub2API Name
 */

var SECRET = PropertiesService.getScriptProperties().getProperty('WEBAPP_SECRET') || 'CHANGE_ME';
var DEFAULT_GID = 0;
var TAB_NAME = 'grok';
var DEFAULT_PASS = '';

function doPost(e) {
  try {
    var body = {};
    if (e && e.postData && e.postData.contents) {
      body = JSON.parse(e.postData.contents);
    }
    if ((body.secret || '') !== SECRET) {
      return jsonOut_({ ok: false, error: 'bad secret' });
    }
    // action=peek | status → đọc sheet (F5 check), không ghi
    var action = String(body.action || 'write').toLowerCase();
    if (action === 'peek' || action === 'status' || action === 'check') {
      return jsonOut_({ ok: true, result: peekGrokTab_(body) });
    }
    return jsonOut_({ ok: true, result: writePayload_(body) });
  } catch (err) {
    return jsonOut_({ ok: false, error: String(err) });
  }
}

function doGet(e) {
  try {
    var p = (e && e.parameter) || {};
    if (p.secret === SECRET && (p.action === 'peek' || p.action === 'status')) {
      return jsonOut_({ ok: true, result: peekGrokTab_({}) });
    }
  } catch (err) {
    return jsonOut_({ ok: false, error: String(err) });
  }
  return jsonOut_({
    ok: true,
    msg: 'Grok success ledger. POST write | POST/GET action=peek&secret=... for status.',
  });
}

/** Đọc tab grok — dùng để agent tự check, không mở browser. */
function peekGrokTab_(body) {
  var ss = (body && body.spreadsheet_id)
    ? SpreadsheetApp.openById(body.spreadsheet_id)
    : SpreadsheetApp.getActiveSpreadsheet();

  var tabs = ss.getSheets().map(function (sh) {
    return { name: sh.getName(), id: sh.getSheetId(), rows: sh.getLastRow() };
  });
  var dash =
    sheetByGid_(ss, DEFAULT_GID) ||
    ss.getSheetByName(TAB_NAME) ||
    ss.getSheets()[0];
  var lastRow = dash.getLastRow();
  var lastCol = Math.max(dash.getLastColumn(), 4);
  var values =
    lastRow > 0 ? dash.getRange(1, 1, lastRow, lastCol).getDisplayValues() : [];

  // Find header row with Email
  var headerIdx = -1;
  for (var i = 0; i < values.length; i++) {
    var c0 = String(values[i][0] || '').trim();
    var c1 = String(values[i][1] || '').toLowerCase();
    if (c0 === '#' && c1.indexOf('email') >= 0) {
      headerIdx = i;
      break;
    }
  }
  var accRows = [];
  if (headerIdx >= 0) {
    for (var r = headerIdx + 1; r < values.length; r++) {
      var email = String(values[r][1] || '');
      if (!email || email.indexOf('@') < 0) {
        // stop at blank / OPS section
        if (!String(values[r][0] || '').trim() && !email) break;
        if (String(values[r][0] || '').indexOf('OPS') >= 0) break;
        continue;
      }
      accRows.push({
        n: values[r][0],
        email: values[r][1],
        password: values[r][2],
        sub2api: values[r][3],
      });
    }
  }

  return {
    file_name: ss.getName(),
    tab: dash.getName(),
    tab_id: dash.getSheetId(),
    all_tabs: tabs,
    last_row: lastRow,
    full_count: accRows.length,
    head: values.slice(0, 8),
    first_acc: accRows.slice(0, 3),
    last_acc: accRows.slice(-3),
    has_fail_emails: values.some(function (row) {
      var t = row.join(' ').toLowerCase();
      return t.indexOf('pqj6ddftuh') >= 0 || t.indexOf('hujdohqtoa') >= 0;
    }),
  };
}

function writePayload_(body) {
  var ss = SpreadsheetApp.openById(
    body.spreadsheet_id || SpreadsheetApp.getActiveSpreadsheet().getId()
  );
  var sIn = body.summary || {};
  var accounts = body.accounts || [];

  // FULL only — columns: # Email Pass Sub2API VPN
  // payload row: [# Tag Email Pass Sub2 Status Date Exported VPN]
  var full = [];
  for (var i = 0; i < accounts.length; i++) {
    var a = accounts[i];
    var tag = String(a[1] || 'FULL').toUpperCase();
    if (tag === 'REG' || tag === 'FAIL') continue;
    var email = a[2] || '';
    var pass = a[3] || '';
    var sub2 = a[4] || '';
    var vpn = a[8] || a[5] || ''; // VPN col (index 8) or fallback
    if (String(email).indexOf('@') < 0 && String(a[0] || '').indexOf('@') >= 0) {
      // alternate layout
      email = a[0]; pass = a[1]; sub2 = a[2]; vpn = a[3] || '';
    }
    full.push([
      full.length + 1,
      email,
      pass,
      sub2,
      vpn || '—',
    ]);
  }

  var s = {
    exported_at: sIn.exported_at || Utilities.formatDate(new Date(), 'Asia/Ho_Chi_Minh', 'yyyy-MM-dd HH:mm:ss'),
    batch_label: sIn.batch_label || '',
    batch_full: sIn.acc_full != null ? sIn.acc_full : '',
    batch_fail: sIn.acc_fail != null ? sIn.acc_fail : '',
    batch_rate: sIn.ok_rate != null ? sIn.ok_rate : '',
    total_full: sIn.alltime_full != null ? sIn.alltime_full : full.length,
    password: sIn.password_common || DEFAULT_PASS,
    vpn_label: sIn.vpn_label || '—',
    vpn_country: sIn.vpn_country || '',
    vpn_ip: sIn.vpn_ip || '',
  };
  if (!s.total_full) s.total_full = full.length;

  try {
    if (ss.getName() !== TAB_NAME) ss.rename(TAB_NAME);
  } catch (e1) {}

  var gid = parseInt(body.gid || DEFAULT_GID, 10);
  var dash = sheetByGid_(ss, gid) || ss.getSheets()[0];
  try {
    var clash = ss.getSheetByName(TAB_NAME);
    if (clash && clash.getSheetId() !== dash.getSheetId()) {
      clash.setName('old_' + clash.getSheetId());
    }
  } catch (e2) {}
  dash.setName(TAB_NAME);
  // Must remove filter BEFORE clear (Google error if filter exists)
  try {
    var oldFilter = dash.getFilter();
    if (oldFilter) oldFilter.remove();
  } catch (eFilter0) {}
  try {
    dash.clear();
  } catch (eClear) {
    // fallback clear contents only
    dash.clearContents();
  }
  try {
    dash.clearFormats();
  } catch (eFmt) {}

  // --- Title (generic, not overnight-only) ---
  dash.getRange(1, 1, 1, 4).merge()
    .setValue('GROK REG  ·  ACC THÀNH CÔNG')
    .setFontWeight('bold').setFontSize(16).setBackground('#1a73e8').setFontColor('#fff')
    .setVerticalAlignment('middle');
  dash.setRowHeight(1, 36);

  // --- Meta ---
  dash.getRange(2, 1).setValue('Cập nhật').setFontWeight('bold').setBackground('#e8f0fe');
  dash.getRange(2, 2, 1, 2).merge().setValue(s.exported_at);
  dash.getRange(3, 1).setValue('Tổng FULL').setFontWeight('bold').setBackground('#e8f0fe');
  dash.getRange(3, 2).setValue(s.total_full).setFontWeight('bold').setFontSize(14);
  dash.getRange(3, 3).setValue('Pass chung').setFontWeight('bold').setBackground('#e8f0fe');
  dash.getRange(3, 4).setValue(s.password);

  // VPN / exit IP (system VPN or proxy → country)
  dash.getRange(4, 1).setValue('VPN / IP').setFontWeight('bold').setBackground('#fef7e0');
  dash.getRange(4, 2, 1, 3).merge().setValue(s.vpn_label || '—')
    .setFontWeight('bold');

  // Optional batch line
  var row = 6;
  if (s.batch_label || s.batch_full !== '') {
    dash.getRange(row, 1).setValue('Lần export này').setFontWeight('bold').setBackground('#e6f4ea');
    var batchTxt = s.batch_label || '';
    if (s.batch_full !== '') {
      batchTxt += (batchTxt ? '  ·  ' : '') +
        'FULL=' + s.batch_full +
        (s.batch_fail !== '' ? '  FAIL=' + s.batch_fail : '') +
        (s.batch_rate !== '' ? '  RATE=' + s.batch_rate + '%' : '');
    }
    dash.getRange(row, 2, 1, 3).merge().setValue(batchTxt);
    row = 8;
  }

  // --- FULL table (success only) + VPN column ---
  dash.getRange(row, 1, 1, 5).merge()
    .setValue('FULL  (email | pass | sub2api_name | VPN)  ·  ' + full.length + ' acc')
    .setFontWeight('bold').setBackground('#e8f0fe');
  row++;
  dash.getRange(row, 1, 1, 5).setValues([['#', 'Email', 'Password', 'Sub2API Name', 'VPN']])
    .setFontWeight('bold').setBackground('#d2e3fc');
  var headerRow = row;
  row++;
  if (full.length) {
    dash.getRange(row, 1, full.length, 5).setValues(full);
    try {
      var oldF2 = dash.getFilter();
      if (oldF2) oldF2.remove();
    } catch (eF) {}
    try {
      dash.getRange(headerRow, 1, full.length + 1, 5).createFilter();
    } catch (eF2) {
      // ignore filter errors — data still written
    }
  } else {
    dash.getRange(row, 1).setValue('(chua co acc FULL)');
  }

  dash.setColumnWidth(1, 50);
  dash.setColumnWidth(2, 300);
  dash.setColumnWidth(3, 180);
  dash.setColumnWidth(4, 150);
  dash.setColumnWidth(5, 220);
  dash.setFrozenRows(headerRow);

  // Remove other tabs — only grok
  deleteOtherTabs_(ss, dash);

  ss.setActiveSheet(dash);
  try { ss.moveActiveSheet(1); } catch (eM) {}
  SpreadsheetApp.flush();

  return { full: full.length, total_full: s.total_full, tab: TAB_NAME, updated: s.exported_at };
}

function deleteOtherTabs_(ss, keep) {
  var sheets = ss.getSheets();
  for (var i = sheets.length - 1; i >= 0; i--) {
    var sh = sheets[i];
    if (sh.getSheetId() === keep.getSheetId()) continue;
    var n = sh.getName();
    if (
      n === 'Acc FULL' || n === 'Acc FAIL' || n === 'Lich su' ||
      n === 'Tong quan' || n.indexOf('grok_old') === 0 || n.indexOf('old_') === 0
    ) {
      try {
        if (ss.getSheets().length > 1) ss.deleteSheet(sh);
      } catch (eDel) {}
    }
  }
}

function sheetByGid_(ss, gid) {
  var sheets = ss.getSheets();
  for (var i = 0; i < sheets.length; i++) {
    if (sheets[i].getSheetId() === gid) return sheets[i];
  }
  return null;
}

function jsonOut_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
