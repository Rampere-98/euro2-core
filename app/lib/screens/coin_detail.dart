import 'package:flutter/material.dart';
import 'chat.dart';
import 'package:provider/provider.dart';

import '../state.dart';
import '../widgets.dart';
import '../widgets/market_block.dart';

class CoinDetailScreen extends StatefulWidget {
  const CoinDetailScreen({super.key, required this.typeId});
  final String typeId;

  @override
  State<CoinDetailScreen> createState() => _CoinDetailScreenState();
}

class _CoinDetailScreenState extends State<CoinDetailScreen> {
  Map<String, dynamic>? _type;
  final Map<String, Map<String, dynamic>> _issues = {};
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final api = context.read<AppState>().api;
    try {
      final t = Map<String, dynamic>.from(await api.get('/types/${widget.typeId}'));
      final issues = List<Map<String, dynamic>>.from(t['issues']);
      final details = await Future.wait(
          issues.map((i) => api.get('/issues/${i['id']}').then((d) => Map<String, dynamic>.from(d))));
      setState(() {
        _type = t;
        for (final d in details) {
          _issues[d['id']] = d;
        }
      });
    } catch (e) {
      setState(() => _error = e);
    }
  }

  Future<void> _addToCollection(Map<String, dynamic> issue) async {
    final state = context.read<AppState>();
    if (!state.loggedIn) {
      showError(context, 'Inicia sesión en Perfil para guardar tu colección');
      return;
    }
    String grade = 'unknown';
    final price = TextEditingController();
    DateTime? when;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setD) => AlertDialog(
          title: const Text('Añadir a mi colección'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            DropdownButtonFormField<String>(
              initialValue: grade,
              decoration: const InputDecoration(labelText: 'Conservación'),
              items: [
                for (final e in kGradeLabel.entries) DropdownMenuItem(value: e.key, child: Text(e.value))
              ],
              onChanged: (v) => setD(() => grade = v ?? 'unknown'),
            ),
            TextField(
              controller: price,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: const InputDecoration(
                  labelText: 'Lo que pagaste (€, opcional)',
                  helperText: 'Alimenta el mercado propio de Euro2: nadie más tiene este dato'),
            ),
            TextButton.icon(
              icon: const Icon(Icons.event),
              label: Text(when == null ? 'Fecha de compra (opcional)' : '${when!.toIso8601String().substring(0, 10)}'),
              onPressed: () async {
                final d = await showDatePicker(
                    context: ctx, firstDate: DateTime(1999), lastDate: DateTime.now(), initialDate: DateTime.now());
                if (d != null) setD(() => when = d);
              },
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Añadir')),
          ],
        ),
      ),
    );
    if (ok != true) return;
    try {
      await state.api.post('/me/collection', body: {
        'issue_id': issue['id'],
        'grade': grade,
        if (price.text.trim().isNotEmpty) 'acquired_price': price.text.trim().replaceAll(',', '.'),
        if (when != null) 'acquired_at': when!.toUtc().toIso8601String(),
      });
      await state.refreshNotifications();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Guardada en tu colección')));
      }
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final api = context.read<AppState>().api;
    final t = _type;
    if (_error != null) return Scaffold(appBar: AppBar(), body: ErrorBox(_error!, onRetry: _load));
    if (t == null) {
      return Scaffold(appBar: AppBar(), body: const Center(child: CircularProgressIndicator()));
    }
    final facts = Map<String, dynamic>.from(t['facts'] ?? {});
    final images = List<Map<String, dynamic>>.from(t['images'] ?? []);
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(t['title'] ?? '')),
      floatingActionButton: AskButton(typeId: t['id']),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Center(
          child: Wrap(spacing: 12, children: [
            for (final img in images)
              Column(mainAxisSize: MainAxisSize.min, children: [
                CoinThumb(api: api, image: img, size: 180),
                Text(img['side'] == 'obverse' ? 'anverso' : img['side'] == 'reverse' ? 'reverso' : 'canto',
                    style: Theme.of(context).textTheme.labelSmall),
                if (img['author'] != null)
                  Text('© ${img['author']}', style: Theme.of(context).textTheme.labelSmall),
              ]),
            if (images.isEmpty)
              Column(mainAxisSize: MainAxisSize.min, children: [
                CoinThumb(api: api, image: null, size: 180),
                const SizedBox(height: 4),
                const Text('Sin foto oficial todavía: el BCE aún no la ha publicado.',
                    style: TextStyle(fontSize: 12), textAlign: TextAlign.center),
              ]),
          ]),
        ),
        if (images.any((i) => i['borrowed'] == true))
          const Padding(
            padding: EdgeInsets.only(top: 6),
            child: Text('Se muestra el diseño base: esta es una edición especial (coloreada, holograma…) de esa moneda.',
                style: TextStyle(fontSize: 12), textAlign: TextAlign.center),
          ),
        const SizedBox(height: 12),
        Text('${countryName(t['country_code'])} · ${t['year']}', style: Theme.of(context).textTheme.titleMedium),
        Wrap(children: [
          if (t['kind'] == 'commemorative') const Chip2('conmemorativa'),
          if (t['kind'] == 'circulation') const Chip2('circulación'),
          if (t['kind'] == 'error') Chip2('error documentado', color: scheme.error),
          if (t['kind'] != 'error' && t['base_type_id'] != null) const Chip2('edición especial'),
          if (t['joint_issue_group'] != null) const Chip2('emisión conjunta'),
          if (t['ecb_ref'] != null) const Chip2('BCE'),
          if (t['numista_type_id'] != null) const Chip2('Numista'),
          if (t['series'] != null) Chip2('serie: ${t['series']}'),
        ]),
        if (t['description'] != null) ...[
          const SizedBox(height: 12),
          Text(t['description'], style: Theme.of(context).textTheme.bodyMedium),
        ],
        const SizedBox(height: 16),
        MarketBlock(typeId: t['id']),
        const SizedBox(height: 16),
        Text('Datos con procedencia', style: Theme.of(context).textTheme.titleMedium),
        for (final e in facts.entries.where((e) => e.key != 'description'))
          _FactRow(name: e.key, fact: Map<String, dynamic>.from(e.value)),
        const SizedBox(height: 16),
        Text('Variantes (${_issues.length})', style: Theme.of(context).textTheme.titleMedium),
        const Text('Cada ceca, acabado y empaquetado es una moneda distinta con su tirada, valor y rareza.',
            style: TextStyle(fontSize: 12)),
        for (final issue in _issues.values) _IssueCard(issue: issue, onAdd: () => _addToCollection(issue)),
      ]),
    );
  }
}

class _FactRow extends StatelessWidget {
  const _FactRow({required this.name, required this.fact});
  final String name;
  final Map<String, dynamic> fact;

  static const _names = {
    'mintage_total': 'Tirada total',
    'kind': 'Tipo',
    'title': 'Título',
    'issue_date_raw': 'Fecha de emisión',
    'joint_issue_group': 'Emisión conjunta',
    'series': 'Serie',
    'topic': 'Motivo',
    'km_reference': 'Referencia KM',
    'composition': 'Composición',
    'diameter_mm': 'Diámetro (mm)',
    'weight_g': 'Peso (g)',
  };

  @override
  Widget build(BuildContext context) {
    final alts = List<Map<String, dynamic>>.from(fact['alternatives'] ?? []);
    final value = fact['value'];
    final shown = value is num && value > 9999 ? fmtInt(value) : '$value';
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      title: Text(_names[name] ?? name),
      subtitle: Text('$shown  · fuente: ${fact['source']}'
          '${fact['has_conflict'] == true ? '\n⚠ Fuentes discrepan: ${alts.map((a) => '${a['source']} dice ${a['value'] is num && a['value'] > 9999 ? fmtInt(a['value']) : a['value']}').join(', ')}' : ''}'),
    );
  }
}

class _IssueCard extends StatelessWidget {
  const _IssueCard({required this.issue, required this.onAdd});
  final Map<String, dynamic> issue;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final rarity = issue['rarity'];
    final estimates = List<Map<String, dynamic>>.from(issue['estimates'] ?? []);
    final label = [
      if ((issue['mint_mark'] as String).isNotEmpty) 'ceca ${issue['mint_mark']}',
      kFinishLabel[issue['finish']] ?? issue['finish'],
      kPackagingLabel[issue['packaging']] ?? issue['packaging'],
      '${issue['year']}',
    ].join(' · ');
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(label, style: Theme.of(context).textTheme.titleSmall)),
            if (rarity != null)
              Chip2('${kTierLabel[rarity['tier']] ?? rarity['tier']} · ${(rarity['score'] as num).round()}/100',
                  color: tierColor(rarity['tier'], scheme)),
          ]),
          Text('Tirada: ${fmtInt(issue['mintage'])}'),
          if (estimates.isEmpty)
            const Text('Sin datos de mercado todavía', style: TextStyle(fontSize: 12))
          else
            for (final e in estimates.where((e) => e['region'] == 'global'))
              Text(
                  '${kGradeLabel[e['grade']] ?? e['grade']}: ${euro(e['median'])}  '
                  '(${kBasisLabel[e['basis']] ?? e['basis']}${e['n_obs'] > 0 ? ', ${e['n_obs']} obs.' : ''})',
                  style: const TextStyle(fontSize: 12)),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton.icon(
                onPressed: onAdd, icon: const Icon(Icons.add), label: const Text('A mi colección')),
          ),
        ]),
      ),
    );
  }
}
