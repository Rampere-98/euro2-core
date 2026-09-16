import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../navigation/swipe_back.dart';
import '../state.dart';
import '../widgets.dart';
import 'coin_detail.dart';

class NewsScreen extends StatefulWidget {
  const NewsScreen({super.key});

  @override
  State<NewsScreen> createState() => _NewsScreenState();
}

class _NewsScreenState extends State<NewsScreen> {
  List<Map<String, dynamic>> _news = [];
  List<Map<String, dynamic>> _reports = [];
  bool _loading = true;
  Object? _error;

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
      final page = await api.get('/news', {'limit': '50'});
      _news = List<Map<String, dynamic>>.from(page['items']);
      _reports = List<Map<String, dynamic>>.from(await api.get('/reports'));
    } catch (e) {
      _error = e;
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _vote(Map<String, dynamic> report, bool approve) async {
    try {
      await context.read<AppState>().api.post('/reports/${report['id']}/vote', body: {'approve': approve});
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  IconData _icon(String kind) => switch (kind) {
        'new_type' => Icons.fiber_new,
        'price_jump' => Icons.trending_up,
        'price_drop' => Icons.trending_down,
        'error_validated' => Icons.verified,
        _ => Icons.article,
      };

  @override
  Widget build(BuildContext context) {
    final isExpert = context.select((AppState s) => s.user?['role'] == 'expert' || s.user?['role'] == 'admin');
    return Scaffold(
      appBar: AppBar(
        title: const Text('Noticias y comunidad'),
        actions: [IconButton(onPressed: _load, icon: const Icon(Icons.refresh))],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? ErrorBox(_error!, onRetry: _load)
              : SectionList(header: [
                  if (_reports.isNotEmpty) ...[
                    Text('Errores de acuñación reportados', style: Theme.of(context).textTheme.titleMedium),
                    const Text('Un error entra en el catálogo cuando dos expertos lo validan.',
                        style: TextStyle(fontSize: 12)),
                    for (final r in _reports)
                      Card(
                        child: ListTile(
                          leading: Icon(r['status'] == 'validated'
                              ? Icons.verified
                              : r['status'] == 'rejected'
                                  ? Icons.cancel
                                  : Icons.hourglass_top),
                          title: Text(r['title']),
                          subtitle: Text('${r['description']}\n'
                              '${kReportStatus[r['status']] ?? r['status']} · '
                              '${r['approvals']} a favor · ${r['rejections']} en contra'),
                          isThreeLine: true,
                          trailing: isExpert && r['status'] == 'pending'
                              ? Row(mainAxisSize: MainAxisSize.min, children: [
                                  IconButton(
                                      icon: const Icon(Icons.thumb_up, color: Colors.green),
                                      onPressed: () => _vote(r, true)),
                                  IconButton(
                                      icon: const Icon(Icons.thumb_down, color: Colors.red),
                                      onPressed: () => _vote(r, false)),
                                ])
                              : null,
                          onTap: () => Navigator.of(context).push(SwipeBackRoute(
                              builder: (_) =>
                                  CoinDetailScreen(typeId: r['created_type_id'] ?? r['base_type_id']))),
                        ),
                      ),
                    const SizedBox(height: 12),
                  ],
                  Text('Novedades del catálogo', style: Theme.of(context).textTheme.titleMedium),
                  if (_news.isEmpty)
                    const Padding(
                        padding: EdgeInsets.all(16),
                        child: Text('Sin noticias aún. Se publican solas cuando el catálogo cambia.')),
                ], itemCount: _news.length, itemBuilder: (context, i) {
                  final n = _news[i];
                  if (n['kind'] == 'bulletin') return _BulletinCard(item: n);
                  return ListTile(
                      leading: Icon(_icon(n['kind'])),
                      title: Text(n['title']),
                      subtitle: Text('${n['body'] ?? ''}\n${'${n['published_at']}'.substring(0, 10)}'),
                      isThreeLine: n['body'] != null,
                      onTap: n['kind'] == 'new_type' || n['kind'] == 'error_validated'
                          ? () => Navigator.of(context).push(SwipeBackRoute(
                              builder: (_) => CoinDetailScreen(typeId: n['entity_id'])))
                          : null,
                    );
                }),
    );
  }
}

const kReportStatus = {'pending': 'pendiente', 'validated': 'validado', 'rejected': 'rechazado'};

/// The daily market bulletin, written by the assistant: headline, date and short sections.
class _BulletinCard extends StatefulWidget {
  const _BulletinCard({required this.item});
  final Map<String, dynamic> item;

  @override
  State<_BulletinCard> createState() => _BulletinCardState();
}

class _BulletinCardState extends State<_BulletinCard> {
  bool _open = false;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final body = (widget.item['body'] ?? '') as String;
    final parts = body.split('\n\n');
    final lead = parts.isNotEmpty ? parts.first : '';
    final sections = parts.skip(1).toList();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(Icons.newspaper, color: Theme.of(context).colorScheme.primary),
            const SizedBox(width: 8),
            Expanded(child: Text(widget.item['title'], style: text.titleLarge)),
          ]),
          const SizedBox(height: 8),
          Text(lead, style: text.bodyMedium),
          if (_open)
            for (final s in sections) ...[
              const SizedBox(height: 12),
              Text(s.split('\n').first, style: text.titleSmall),
              Text(s.split('\n').skip(1).join('\n'), style: text.bodyMedium),
            ],
          if (sections.isNotEmpty)
            Align(
              alignment: Alignment.centerRight,
              child: TextButton(
                onPressed: () => setState(() => _open = !_open),
                child: Text(_open ? 'Cerrar' : 'Leer el boletín'),
              ),
            ),
        ]),
      ),
    );
  }
}
