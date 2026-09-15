import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../navigation/swipe_back.dart';
import '../state.dart';
import '../widgets.dart';
import 'coin_detail.dart';

class CollectionScreen extends StatefulWidget {
  const CollectionScreen({super.key});

  @override
  State<CollectionScreen> createState() => _CollectionScreenState();
}

class _CollectionScreenState extends State<CollectionScreen> {
  List<Map<String, dynamic>> _items = [];
  Map<String, dynamic>? _worth;
  List<Map<String, dynamic>> _achievements = [];
  bool _loading = true;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final state = context.read<AppState>();
    if (!state.loggedIn) {
      setState(() => _loading = false);
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final col = await state.api.get('/me/collection');
      final ach = await state.api.get('/me/achievements');
      setState(() {
        _items = List<Map<String, dynamic>>.from(col['items']);
        _worth = Map<String, dynamic>.from(col['net_worth']);
        _achievements = List<Map<String, dynamic>>.from(ach);
      });
    } catch (e) {
      setState(() => _error = e);
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _verify(Map<String, dynamic> item) async {
    final file = await ImagePicker().pickImage(source: ImageSource.camera, maxWidth: 1600, imageQuality: 90);
    if (file == null || !mounted) return;
    final api = context.read<AppState>().api;
    try {
      await api.upload('/me/collection/${item['id']}/verify', await file.readAsBytes(), 'piece.jpg');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Pieza verificada: ya puedes publicarla en el mercado')));
      }
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _remove(Map<String, dynamic> item) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('¿Quitar de la colección?'),
        content: Text(item['type']['title'] ?? ''),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Quitar')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      await context.read<AppState>().api.delete('/me/collection/${item['id']}');
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _showHistory(Map<String, dynamic> item) async {
    final api = context.read<AppState>().api;
    try {
      final events = List<Map<String, dynamic>>.from(await api.get('/me/collection/${item['id']}/history'));
      final cert = await api.get('/me/collection/${item['id']}/certificate');
      if (!mounted) return;
      showModalBottomSheet(
        context: context,
        showDragHandle: true,
        builder: (_) => ListView(padding: const EdgeInsets.all(16), children: [
          Text('Trazabilidad', style: Theme.of(context).textTheme.titleMedium),
          for (final e in events)
            ListTile(
              dense: true,
              leading: const Icon(Icons.timeline),
              title: Text(_eventLabel(e['kind'])),
              subtitle: Text('${e['at']}'.substring(0, 16).replaceAll('T', ' ') +
                  (e['price'] != null ? ' · ${euro(e['price'])}' : '')),
            ),
          const Divider(),
          Text('Certificado firmado', style: Theme.of(context).textTheme.titleMedium),
          SelectableText('digest: ${cert['digest']}\nfirma: ${cert['signature']}',
              style: const TextStyle(fontSize: 11, fontFamily: 'monospace')),
          const Text('Cualquiera puede comprobar este certificado en POST /certificates/{id}/verify.',
              style: TextStyle(fontSize: 11)),
        ]),
      );
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  static String _eventLabel(String kind) => switch (kind) {
        'added' => 'Añadida a la colección',
        'verified' => 'Verificada por foto',
        'sold' => 'Vendida',
        'traded' => 'Intercambiada',
        'bought' => 'Comprada',
        _ => kind,
      };

  @override
  Widget build(BuildContext context) {
    final loggedIn = context.select((AppState s) => s.loggedIn);
    if (!loggedIn) {
      return Scaffold(
        appBar: AppBar(title: const Text('Mi colección')),
        body: const Center(
            child: Padding(
          padding: EdgeInsets.all(24),
          child: Text('Inicia sesión en Perfil para guardar tus monedas, ver su valor y desbloquear logros.',
              textAlign: TextAlign.center),
        )),
      );
    }
    final worth = _worth;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Mi colección'),
        actions: [IconButton(onPressed: _load, icon: const Icon(Icons.refresh))],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? ErrorBox(_error!, onRetry: _load)
              : RefreshIndicator(
                  onRefresh: _load,
                  child: SectionList(header: [
                    if (worth != null) _WorthCard(worth: worth),
                    if (_achievements.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Text('Logros', style: Theme.of(context).textTheme.titleMedium),
                      Wrap(children: [
                        for (final a in _achievements)
                          Chip2(achievementLabel(a), color: Colors.amber),
                      ]),
                    ],
                    const SizedBox(height: 8),
                    Text('Piezas (${_items.length})', style: Theme.of(context).textTheme.titleMedium),
                    if (_items.isEmpty)
                      const Padding(
                        padding: EdgeInsets.all(16),
                        child: Text('Todavía no tienes monedas. Escanea una o búscala en el catálogo.'),
                      ),
                  ], itemCount: _items.length, itemBuilder: (context, i) {
                    final item = _items[i];
                    return _ItemCard(
                      item: item,
                      onOpen: () => Navigator.of(context).push(SwipeBackRoute(
                          builder: (_) => CoinDetailScreen(typeId: item['type']['id']))),
                      onVerify: () => _verify(item),
                      onHistory: () => _showHistory(item),
                      onRemove: () => _remove(item),
                    );
                  }),
                ),
    );
  }
}

const kAchievementLabel = {
  'first_coin': 'Primera moneda',
  'ten_coins': 'Diez monedas',
  'fifty_coins': 'Cincuenta monedas',
  'two_hundred': 'Doscientas monedas',
  'verified_piece': 'Pieza verificada',
  'rare_hunter': 'Cazador de rarezas',
};

String achievementLabel(Map<String, dynamic> a) {
  final code = a['code'] as String;
  if (kAchievementLabel.containsKey(code)) return kAchievementLabel[code]!;
  final key = code.contains(':') ? code.substring(code.indexOf(':') + 1) : code;
  if (code.startsWith('country_complete')) return 'Pais completo: ${countryName(key)}';
  if (code.startsWith('joint_complete')) return 'Emision conjunta completa: $key';
  return code;
}

class _WorthCard extends StatelessWidget {
  const _WorthCard({required this.worth});
  final Map<String, dynamic> worth;

  @override
  Widget build(BuildContext context) {
    final byBasis = Map<String, dynamic>.from(worth['value_by_basis'] ?? {});
    final gain = double.tryParse('${worth['gain']}') ?? 0;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Valor estimado', style: Theme.of(context).textTheme.labelLarge),
          Text(euro(worth['value']), style: Theme.of(context).textTheme.headlineMedium),
          Text('${worth['pieces']} piezas · coste ${euro(worth['cost'])} · '
              '${gain >= 0 ? '+' : ''}${euro(gain)}'),
          const SizedBox(height: 6),
          for (final e in byBasis.entries)
            Text('${kBasisLabel[e.key] ?? e.key}: ${euro(e.value)}', style: const TextStyle(fontSize: 12)),
          const SizedBox(height: 4),
          const Text(
            'Solo "ventas reales" es un valor de mercado; el resto son referencias (catálogo, precios pedidos o valor facial).',
            style: TextStyle(fontSize: 11),
          ),
        ]),
      ),
    );
  }
}

class _ItemCard extends StatelessWidget {
  const _ItemCard({
    required this.item,
    required this.onOpen,
    required this.onVerify,
    required this.onHistory,
    required this.onRemove,
  });
  final Map<String, dynamic> item;
  final VoidCallback onOpen, onVerify, onHistory, onRemove;

  @override
  Widget build(BuildContext context) {
    final api = context.read<AppState>().api;
    final type = Map<String, dynamic>.from(item['type']);
    final issue = Map<String, dynamic>.from(item['issue']);
    final val = Map<String, dynamic>.from(item['valuation']);
    final verified = item['verified_at'] != null;
    return Card(
      child: Column(children: [
        TypeTile(
          api: api,
          type: type,
          onTap: onOpen,
          trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(euro(val['value']), style: Theme.of(context).textTheme.titleMedium),
            Text(kBasisLabel[val['basis']] ?? val['basis'], style: const TextStyle(fontSize: 10)),
          ]),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 8, 6),
          child: Row(children: [
            Expanded(
              child: Wrap(children: [
                Chip2(kGradeLabel[item['grade']] ?? item['grade']),
                Chip2(kFinishLabel[issue['finish']] ?? issue['finish']),
                if ((issue['mint_mark'] as String).isNotEmpty) Chip2('ceca ${issue['mint_mark']}'),
                if (verified) const Chip2('verificada', color: Colors.green),
              ]),
            ),
            PopupMenuButton<String>(
              onSelected: (v) => switch (v) {
                'verify' => onVerify(),
                'history' => onHistory(),
                _ => onRemove(),
              },
              itemBuilder: (_) => [
                if (!verified) const PopupMenuItem(value: 'verify', child: Text('Verificar con foto')),
                const PopupMenuItem(value: 'history', child: Text('Trazabilidad y certificado')),
                const PopupMenuItem(value: 'remove', child: Text('Quitar')),
              ],
            ),
          ]),
        ),
      ]),
    );
  }
}
