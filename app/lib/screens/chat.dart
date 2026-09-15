import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state.dart';
import '../widgets.dart';
import '../widgets/market_block.dart';
import 'coin_detail.dart';

class _Msg {
  _Msg(this.text, {required this.mine, this.typeIds = const [], this.links = const [], this.suggestions = const []});
  final String text;
  final bool mine;
  final List<String> typeIds;
  final List<Map<String, dynamic>> links;
  final List<String> suggestions;
}

/// The app's own assistant: everything is answered locally from the catalog and market.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, this.typeId});
  final String? typeId; // coin the user was looking at, if any

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final List<_Msg> _msgs = [];
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _msgs.add(_Msg(
      'Hola, soy el asistente de Euro2. Todo lo que respondo sale de tu propio catálogo y del mercado observado: nada se consulta fuera.',
      mine: false,
      suggestions: const ['¿Cuánto vale la de Grace Kelly?', '¿Hay chollos hoy?', '¿Qué significa BU?', '¿Cómo vendo una moneda?'],
    ));
  }

  Future<void> _send([String? preset]) async {
    final text = (preset ?? _input.text).trim();
    if (text.isEmpty || _busy) return;
    _input.clear();
    setState(() {
      _msgs.add(_Msg(text, mine: true));
      _busy = true;
    });
    _jump();
    try {
      final api = context.read<AppState>().api;
      final r = Map<String, dynamic>.from(await api.post('/assistant/chat', body: {
        'message': text,
        if (widget.typeId != null) 'type_id': widget.typeId,
      }));
      setState(() => _msgs.add(_Msg(
            r['text'],
            mine: false,
            typeIds: List<String>.from(r['type_ids'] ?? []),
            links: List<Map<String, dynamic>>.from(r['links'] ?? []),
            suggestions: List<String>.from(r['suggestions'] ?? []),
          )));
    } catch (e) {
      setState(() => _msgs.add(_Msg('No he podido responder: $e', mine: false)));
    }
    if (mounted) setState(() => _busy = false);
    _jump();
  }

  void _jump() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
      });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Asistente')),
      body: Column(children: [
        Expanded(
          child: ListView.builder(
            controller: _scroll,
            padding: const EdgeInsets.all(12),
            itemCount: _msgs.length,
            itemBuilder: (_, i) {
              final m = _msgs[i];
              return Column(
                crossAxisAlignment: m.mine ? CrossAxisAlignment.end : CrossAxisAlignment.start,
                children: [
                  Container(
                    margin: const EdgeInsets.symmetric(vertical: 4),
                    padding: const EdgeInsets.all(12),
                    constraints: const BoxConstraints(maxWidth: 560),
                    decoration: BoxDecoration(
                      color: m.mine ? scheme.primaryContainer : scheme.surfaceContainerHighest,
                      borderRadius: BorderRadius.circular(14),
                    ),
                    child: SelectableText(m.text),
                  ),
                  if (m.typeIds.isNotEmpty || m.links.isNotEmpty)
                    Wrap(spacing: 6, children: [
                      for (final id in m.typeIds.take(3))
                        ActionChip(
                          avatar: const Icon(Icons.euro, size: 16),
                          label: const Text('Ver moneda'),
                          onPressed: () => Navigator.of(context)
                              .push(MaterialPageRoute(builder: (_) => CoinDetailScreen(typeId: id))),
                        ),
                      for (final l in m.links.take(3))
                        ActionChip(
                          avatar: const Icon(Icons.open_in_new, size: 16),
                          label: Text(l['label'] ?? 'anuncio', overflow: TextOverflow.ellipsis),
                          onPressed: () => openUrl(context, l['url']),
                        ),
                    ]),
                  if (m.suggestions.isNotEmpty)
                    Wrap(spacing: 6, children: [
                      for (final s in m.suggestions)
                        ActionChip(label: Text(s), onPressed: () => _send(s)),
                    ]),
                ],
              );
            },
          ),
        ),
        if (_busy) const LinearProgressIndicator(),
        SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 12),
            child: Row(children: [
              Expanded(
                child: TextField(
                  controller: _input,
                  onSubmitted: (_) => _send(),
                  decoration: const InputDecoration(
                    hintText: 'Pregunta sobre cualquier moneda de 2 €…',
                    border: OutlineInputBorder(),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(onPressed: () => _send(), icon: const Icon(Icons.send)),
            ]),
          ),
        ),
      ]),
    );
  }
}

/// Floating entry point used by every screen.
class AskButton extends StatelessWidget {
  const AskButton({super.key, this.typeId});
  final String? typeId;

  @override
  Widget build(BuildContext context) => FloatingActionButton.extended(
        heroTag: 'ask-$typeId',
        onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => ChatScreen(typeId: typeId))),
        icon: const Icon(Icons.chat_bubble_outline),
        label: const Text('Pregunta'),
      );
}

String euroOrDash(dynamic v) => v == null ? '—' : euro(v);
