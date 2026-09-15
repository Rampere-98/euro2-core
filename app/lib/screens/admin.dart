import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state.dart';
import '../widgets.dart';
import '../widgets/market_block.dart';

/// Server administration, entirely from the app: keys, sources, users, server, logs, upkeep.
class AdminScreen extends StatelessWidget {
  const AdminScreen({super.key});

  @override
  Widget build(BuildContext context) => DefaultTabController(
        length: 6,
        child: Scaffold(
          appBar: AppBar(
            title: const Text('Administración'),
            bottom: const TabBar(isScrollable: true, tabs: [
              Tab(icon: Icon(Icons.key), text: 'Claves'),
              Tab(icon: Icon(Icons.sync), text: 'Fuentes'),
              Tab(icon: Icon(Icons.people), text: 'Usuarios'),
              Tab(icon: Icon(Icons.tune), text: 'Servidor'),
              Tab(icon: Icon(Icons.receipt_long), text: 'Registros'),
              Tab(icon: Icon(Icons.build), text: 'Mantenimiento'),
            ]),
          ),
          body: const TabBarView(children: [
            _KeysTab(),
            _JobsTab(),
            _UsersTab(),
            _ServerTab(),
            _LogsTab(),
            _MaintenanceTab(),
          ]),
        ),
      );
}

// ------------------------------------------------------------------ shared

class _SettingsForm extends StatefulWidget {
  const _SettingsForm({required this.keys, this.testable = const {}});
  final List<String> keys; // which settings this tab edits
  final Map<String, String> testable; // key -> source to test

  @override
  State<_SettingsForm> createState() => _SettingsFormState();
}

class _SettingsFormState extends State<_SettingsForm> with AutomaticKeepAliveClientMixin {
  Map<String, Map<String, dynamic>> _view = {};
  final Map<String, TextEditingController> _ctrl = {};
  final Map<String, bool> _bools = {};
  final Map<String, String> _testResult = {};
  bool _loading = true;
  Object? _error;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = context.read<AppState>().api;
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final rows = List<Map<String, dynamic>>.from(await api.get('/admin/settings'));
      _view = {for (final r in rows) r['key'] as String: r};
      for (final k in widget.keys) {
        final v = _view[k];
        if (v == null) continue;
        if (v['kind'] == 'bool') {
          _bools[k] = v['value'] == true;
        } else {
          final text = v['secret'] == true ? '' : (v['kind'] == 'json' ? _json(v['value']) : '${v['value']}');
          _ctrl[k] = TextEditingController(text: text);
        }
      }
    } catch (e) {
      _error = e;
    }
    if (mounted) setState(() => _loading = false);
  }

  String _json(dynamic v) => v is List ? v.map((e) => e is List ? e.join(', ') : e.toString()).join('\n') : '$v';

  dynamic _parse(Map<String, dynamic> spec, String text) {
    final t = text.trim();
    if (t.isEmpty) return '';
    switch (spec['kind']) {
      case 'float':
        return double.tryParse(t.replaceAll(',', '.')) ?? t;
      case 'int':
        return int.tryParse(t) ?? t;
      case 'json':
        final lines = t.split('\n').map((l) => l.trim()).where((l) => l.isNotEmpty);
        if (spec['key'] == 'mintage_buckets') {
          return [
            for (final l in lines) l.split(',').map((x) => double.tryParse(x.trim()) ?? 0).toList(),
          ];
        }
        return lines.toList();
      default:
        return t;
    }
  }

  Future<void> _save() async {
    final api = context.read<AppState>().api;
    final values = <String, dynamic>{};
    for (final k in widget.keys) {
      final spec = _view[k];
      if (spec == null) continue;
      if (spec['kind'] == 'bool') {
        values[k] = _bools[k] ?? false;
      } else {
        final text = _ctrl[k]!.text;
        if (spec['secret'] == true && text.trim().isEmpty) continue; // untouched secret
        values[k] = _parse(spec, text);
      }
    }
    try {
      await api.put('/admin/settings', body: {'values': values});
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Guardado en el servidor')));
      }
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _clear(String key) async {
    try {
      await context.read<AppState>().api.put('/admin/settings', body: {
        'values': {key: ''}
      });
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _test(String key) async {
    final api = context.read<AppState>().api;
    setState(() => _testResult[key] = 'probando…');
    try {
      final r = await api.post('/admin/settings/test', body: {'source': widget.testable[key]});
      setState(() => _testResult[key] = '${r['ok'] == true ? '✔' : '✖'} ${r['detail']}');
    } catch (e) {
      setState(() => _testResult[key] = '✖ $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return ErrorBox(_error!, onRetry: _load);
    return ListView(padding: const EdgeInsets.all(16), children: [
      for (final k in widget.keys)
        if (_view[k] case final spec?)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: spec['kind'] == 'bool'
                ? SwitchListTile(
                    title: Text(spec['label']),
                    subtitle: spec['help'] != '' ? Text(spec['help']) : null,
                    value: _bools[k] ?? false,
                    onChanged: (v) => setState(() => _bools[k] = v),
                  )
                : Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    TextField(
                      controller: _ctrl[k],
                      obscureText: spec['secret'] == true,
                      maxLines: spec['kind'] == 'json' ? 4 : 1,
                      decoration: InputDecoration(
                        labelText: spec['label'],
                        helperText: [
                          if (spec['help'] != '') spec['help'],
                          if (spec['secret'] == true)
                            spec['set'] == true ? 'guardada: ${spec['value']} (origen: ${spec['source']})' : 'no configurada',
                          if (spec['secret'] != true) 'origen: ${_source(spec['source'])}',
                        ].join(' · '),
                        border: const OutlineInputBorder(),
                        suffixIcon: spec['source'] == 'app'
                            ? IconButton(
                                tooltip: 'Quitar (volver al valor por defecto)',
                                icon: const Icon(Icons.restart_alt),
                                onPressed: () => _clear(k))
                            : null,
                      ),
                    ),
                    if (widget.testable.containsKey(k))
                      Row(children: [
                        TextButton.icon(
                            onPressed: () => _test(k),
                            icon: const Icon(Icons.play_arrow),
                            label: const Text('Probar con la clave guardada')),
                        Expanded(child: Text(_testResult[k] ?? '', style: const TextStyle(fontSize: 12))),
                      ]),
                  ]),
          ),
      FilledButton.icon(onPressed: _save, icon: const Icon(Icons.save), label: const Text('Guardar')),
      const SizedBox(height: 8),
      const Text('Los cambios se guardan cifrados en el servidor y se aplican sin reiniciar.',
          style: TextStyle(fontSize: 12)),
    ]);
  }

  String _source(String s) => switch (s) {
        'app' => 'ajustado aquí',
        'env' => 'archivo .env del servidor',
        _ => 'valor por defecto',
      };
}

// ------------------------------------------------------------------ tabs

class _KeysTab extends StatelessWidget {
  const _KeysTab();

  @override
  Widget build(BuildContext context) => const _SettingsForm(
        keys: ['numista_api_key', 'ebay_client_id', 'ebay_client_secret'],
        testable: {'numista_api_key': 'numista', 'ebay_client_secret': 'ebay'},
      );
}

class _ServerTab extends StatelessWidget {
  const _ServerTab();

  @override
  Widget build(BuildContext context) => const _SettingsForm(keys: [
        'registration_open',
        'public_origins',
        'duckdns_domain',
        'duckdns_token',
        'user_agent',
        'deal_threshold_pct',
        'replica_words',
        'altered_words',
        'mintage_buckets',
      ]);
}

class _JobsTab extends StatefulWidget {
  const _JobsTab();

  @override
  State<_JobsTab> createState() => _JobsTabState();
}

class _JobsTabState extends State<_JobsTab> with AutomaticKeepAliveClientMixin {
  List<Map<String, dynamic>> _jobs = [];
  Object? _error;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final rows = await context.read<AppState>().api.get('/admin/jobs');
      setState(() {
        _jobs = List<Map<String, dynamic>>.from(rows);
        _error = null;
      });
    } catch (e) {
      setState(() => _error = e);
    }
  }

  Future<void> _patch(String job, Map<String, dynamic> body) async {
    try {
      await context.read<AppState>().api.patch('/admin/jobs/$job', body: body);
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _run(String job) async {
    try {
      await context.read<AppState>().api.post('/admin/jobs/$job/run');
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$job en marcha')));
      await Future.delayed(const Duration(seconds: 2));
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _cadence(Map<String, dynamic> j) async {
    final ctrl = TextEditingController(text: '${j['interval_hours']}');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(j['label']),
        content: TextField(
          controller: ctrl,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: const InputDecoration(labelText: 'Cada cuántas horas'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Guardar')),
        ],
      ),
    );
    if (ok == true) {
      final h = double.tryParse(ctrl.text.replaceAll(',', '.'));
      if (h != null && h > 0) await _patch(j['job'], {'interval_hours': h});
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    if (_error != null) return ErrorBox(_error!, onRetry: _load);
    if (_jobs.isEmpty) return const Center(child: CircularProgressIndicator());
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(8), children: [
        for (final j in _jobs)
          Card(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SwitchListTile(
                title: Text(j['label']),
                subtitle: Text(_status(j)),
                value: j['enabled'] == true,
                onChanged: (v) => _patch(j['job'], {'enabled': v}),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 8, 8),
                child: Wrap(spacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  ActionChip(
                      avatar: const Icon(Icons.schedule, size: 16),
                      label: Text('cada ${_hours(j['interval_hours'])}'),
                      onPressed: () => _cadence(j)),
                  if (j['needs'] != null && j['has_credentials'] != true)
                    const Chip2('sin clave: se omite', color: Colors.orange),
                  FilledButton.tonal(
                    onPressed: j['running'] == true ? null : () => _run(j['job']),
                    child: Text(j['running'] == true ? 'En ejecución…' : 'Ejecutar ahora'),
                  ),
                ]),
              ),
              if (j['last_error'] != null && (j['last_error'] as String).isNotEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                  child: Text(j['last_error'], style: const TextStyle(fontSize: 11, color: Colors.red)),
                ),
            ]),
          ),
      ]),
    );
  }

  String _hours(dynamic h) {
    final v = (h as num).toDouble();
    if (v < 1) return '${(v * 60).round()} min';
    if (v % 24 == 0 && v >= 24) return '${(v / 24).round()} d';
    return '${v.toStringAsFixed(v == v.roundToDouble() ? 0 : 1)} h';
  }

  String _status(Map<String, dynamic> j) {
    final status = j['last_status'];
    if (status == null) return 'nunca ejecutado';
    final when = (j['last_finished_at'] ?? j['last_started_at'] ?? '').toString();
    final label = switch (status) {
      'succeeded' => 'correcto',
      'failed' => 'fallido (se reintenta en 1 h)',
      'running' => 'en ejecución',
      _ => status.toString(),
    };
    final stats = j['last_stats'];
    return '$label · ${when.length >= 16 ? when.substring(0, 16).replaceAll('T', ' ') : when}'
        '${stats is Map && stats.isNotEmpty ? '\n${stats.entries.take(4).map((e) => '${e.key}: ${e.value}').join(' · ')}' : ''}';
  }
}

class _UsersTab extends StatefulWidget {
  const _UsersTab();

  @override
  State<_UsersTab> createState() => _UsersTabState();
}

class _UsersTabState extends State<_UsersTab> with AutomaticKeepAliveClientMixin {
  final _q = TextEditingController();
  List<Map<String, dynamic>> _users = [];

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final rows = await context.read<AppState>().api.get('/admin/users', {
        if (_q.text.trim().isNotEmpty) 'q': _q.text.trim(),
      });
      setState(() => _users = List<Map<String, dynamic>>.from(rows));
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _patch(Map<String, dynamic> u, Map<String, dynamic> body) async {
    try {
      await context.read<AppState>().api.patch('/admin/users/${u['id']}', body: body);
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return Column(children: [
      Padding(
        padding: const EdgeInsets.all(12),
        child: TextField(
          controller: _q,
          onSubmitted: (_) => _load(),
          decoration: InputDecoration(
            hintText: 'Buscar por email o nombre',
            prefixIcon: IconButton(icon: const Icon(Icons.search), onPressed: _load),
            border: const OutlineInputBorder(),
          ),
        ),
      ),
      Expanded(
        child: ListView(children: [
          for (final u in _users)
            ListTile(
              leading: CircleAvatar(child: Text((u['display_name'] as String).substring(0, 1).toUpperCase())),
              title: Text('${u['display_name']} · ${u['email']}'),
              subtitle: Text('${u['role']} · plan ${u['plan']} · ${(u['created_at'] as String).substring(0, 10)}'),
              trailing: PopupMenuButton<String>(
                onSelected: (v) => switch (v) {
                  'user' || 'expert' || 'admin' => _patch(u, {'role': v}),
                  _ => _patch(u, {'plan': v}),
                },
                itemBuilder: (_) => const [
                  PopupMenuItem(value: 'user', child: Text('Rol: usuario')),
                  PopupMenuItem(value: 'expert', child: Text('Rol: experto')),
                  PopupMenuItem(value: 'admin', child: Text('Rol: administrador')),
                  PopupMenuDivider(),
                  PopupMenuItem(value: 'free', child: Text('Plan: gratuito')),
                  PopupMenuItem(value: 'pro', child: Text('Plan: Pro')),
                ],
              ),
            ),
        ]),
      ),
    ]);
  }
}

class _LogsTab extends StatefulWidget {
  const _LogsTab();

  @override
  State<_LogsTab> createState() => _LogsTabState();
}

class _LogsTabState extends State<_LogsTab> with AutomaticKeepAliveClientMixin {
  List<String> _lines = [];
  List<Map<String, dynamic>> _runs = [];

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = context.read<AppState>().api;
    try {
      final lines = await api.get('/admin/logs', {'lines': '200'});
      final runs = await api.get('/sync/runs', {'limit': '15'});
      setState(() {
        _lines = List<String>.from(lines);
        _runs = List<Map<String, dynamic>>.from(runs['items']);
      });
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(12), children: [
        Row(children: [
          Text('Últimas ejecuciones', style: Theme.of(context).textTheme.titleMedium),
          const Spacer(),
          IconButton(onPressed: _load, icon: const Icon(Icons.refresh)),
        ]),
        for (final r in _runs)
          ListTile(
            dense: true,
            leading: Icon(
              r['status'] == 'succeeded' ? Icons.check_circle : r['status'] == 'failed' ? Icons.error : Icons.play_circle,
              color: r['status'] == 'succeeded' ? Colors.green : r['status'] == 'failed' ? Colors.red : null,
            ),
            title: Text('${r['job']} · ${r['status']}'),
            subtitle: Text('${(r['started_at'] as String).substring(0, 16).replaceAll('T', ' ')}'
                '${r['error'] != null ? '\n${(r['error'] as String).split('\n').first}' : ''}'),
          ),
        const SizedBox(height: 12),
        Text('Registro del servidor', style: Theme.of(context).textTheme.titleMedium),
        Container(
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surfaceContainerHighest, borderRadius: BorderRadius.circular(8)),
          child: SelectableText(_lines.isEmpty ? 'sin líneas todavía' : _lines.join('\n'),
              style: const TextStyle(fontSize: 10, fontFamily: 'monospace')),
        ),
      ]),
    );
  }
}

class _MaintenanceTab extends StatefulWidget {
  const _MaintenanceTab();

  @override
  State<_MaintenanceTab> createState() => _MaintenanceTabState();
}

class _MaintenanceTabState extends State<_MaintenanceTab> with AutomaticKeepAliveClientMixin {
  Map<String, dynamic>? _stats;
  Map<String, dynamic>? _version;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = context.read<AppState>().api;
    try {
      final s = await api.get('/admin/stats');
      final v = await api.get('/admin/version');
      setState(() {
        _stats = Map<String, dynamic>.from(s);
        _version = Map<String, dynamic>.from(v);
      });
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _run(String job) async {
    try {
      await context.read<AppState>().api.post('/admin/jobs/$job/run');
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$job en marcha')));
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _update() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('¿Actualizar el servidor?'),
        content: const Text('Se descarga la última imagen publicada y se reinicia la API (≈ 1 minuto sin servicio).'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Actualizar')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await context.read<AppState>().api.post('/admin/update');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Actualizando… vuelve en un minuto')));
      }
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final api = context.read<AppState>().api;
    final s = _stats;
    final v = _version;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text('Estado', style: Theme.of(context).textTheme.titleMedium),
      if (s != null)
        Wrap(spacing: 8, runSpacing: 8, children: [
          _Stat('Monedas', '${s['types']}'),
          _Stat('Variantes', '${s['issues']}'),
          _Stat('Fotos', '${s['images_local']}'),
          _Stat('Usuarios', '${s['users']}'),
          _Stat('Piezas en colecciones', '${s['collection_items']}'),
          for (final e in (s['observations_by_source'] as Map).entries)
            _Stat('Observaciones ${e.key}', '${e.value}'),
        ]),
      const SizedBox(height: 16),
      Text('Versión', style: Theme.of(context).textTheme.titleMedium),
      if (v != null)
        ListTile(
          leading: Icon(v['update_available'] == true ? Icons.system_update : Icons.verified, color: v['update_available'] == true ? Colors.orange : Colors.green),
          title: Text('Euro2 ${v['version']}'),
          subtitle: Text(v['updater'] != true
              ? 'Instalación local: actualiza con git pull'
              : v['update_available'] == true
                  ? 'Hay una versión nueva publicada'
                  : 'Al día'),
          trailing: v['updater'] == true
              ? FilledButton(onPressed: _update, child: const Text('Actualizar'))
              : null,
        ),
      const SizedBox(height: 16),
      Text('Recalcular', style: Theme.of(context).textTheme.titleMedium),
      Wrap(spacing: 8, children: [
        for (final e in const {
          'recompute_prices': 'Precios y modelo',
          'recompute_rarity': 'Rareza',
          'embed_images': 'Índice de fotos',
          'embed_types': 'Índice semántico',
          'publish_news': 'Noticias',
        }.entries)
          ActionChip(label: Text(e.value), onPressed: () => _run(e.key)),
      ]),
      const SizedBox(height: 16),
      Text('Copia de seguridad', style: Theme.of(context).textTheme.titleMedium),
      ListTile(
        leading: const Icon(Icons.download),
        title: const Text('Descargar copia completa (pg_dump)'),
        subtitle: const Text('Incluye catálogo, usuarios y colecciones. Guárdala fuera del servidor.'),
        onTap: () => openUrl(context, '${api.baseUrl}/admin/backup?token=${api.token}'),
      ),
      const Text('Las copias nocturnas automáticas se guardan en el disco del servidor (14 días).',
          style: TextStyle(fontSize: 12)),
    ]);
  }
}

class _Stat extends StatelessWidget {
  const _Stat(this.label, this.value);
  final String label, value;

  @override
  Widget build(BuildContext context) => Container(
        width: 150,
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.surfaceContainerHighest, borderRadius: BorderRadius.circular(10)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: Theme.of(context).textTheme.labelSmall),
          Text(value, style: Theme.of(context).textTheme.titleMedium),
        ]),
      );
}
