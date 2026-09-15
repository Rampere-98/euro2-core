import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state.dart';
import '../widgets.dart';
import 'coin_detail.dart';

const kOfferStatus = {
  'pending': 'pendiente',
  'accepted': 'aceptada',
  'rejected': 'rechazada',
  'withdrawn': 'retirada',
};

/// Listings between verified collectors: publish, offer, accept/reject, rate.
class PeerMarketTab extends StatefulWidget {
  const PeerMarketTab({super.key});

  @override
  State<PeerMarketTab> createState() => _PeerMarketTabState();
}

class _PeerMarketTabState extends State<PeerMarketTab> with AutomaticKeepAliveClientMixin {
  List<Map<String, dynamic>> _listings = [];
  List<Map<String, dynamic>> _myOffers = [];
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
    final state = context.read<AppState>();
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final page = await state.api.get('/market/listings', {'limit': '50'});
      _listings = List<Map<String, dynamic>>.from(page['items']);
      _myOffers = state.loggedIn
          ? List<Map<String, dynamic>>.from(await state.api.get('/me/offers'))
          : [];
    } catch (e) {
      _error = e;
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _publish() async {
    final state = context.read<AppState>();
    if (!state.loggedIn) {
      showError(context, 'Inicia sesión para vender');
      return;
    }
    final col = await state.api.get('/me/collection');
    final verified = List<Map<String, dynamic>>.from(col['items'])
        .where((i) => i['verified_at'] != null)
        .toList();
    if (!mounted) return;
    if (verified.isEmpty) {
      showError(context, 'Solo se publican piezas verificadas con foto (Colección → Verificar)');
      return;
    }
    Map<String, dynamic>? chosen = verified.first;
    final price = TextEditingController();
    final desc = TextEditingController();
    bool trades = true;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setD) => AlertDialog(
          title: const Text('Publicar en el mercado'),
          content: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              DropdownButtonFormField<Map<String, dynamic>>(
                initialValue: chosen,
                isExpanded: true,
                decoration: const InputDecoration(labelText: 'Pieza verificada'),
                items: [
                  for (final v in verified)
                    DropdownMenuItem(
                        value: v,
                        child: Text(v['type']['title'] ?? '', overflow: TextOverflow.ellipsis)),
                ],
                onChanged: (v) => setD(() => chosen = v),
              ),
              TextField(
                controller: price,
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                decoration: const InputDecoration(labelText: 'Precio (€) — vacío = solo intercambio'),
              ),
              TextField(controller: desc, decoration: const InputDecoration(labelText: 'Descripción')),
              SwitchListTile(
                value: trades,
                onChanged: (v) => setD(() => trades = v),
                title: const Text('Acepto intercambios'),
                contentPadding: EdgeInsets.zero,
              ),
            ]),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Publicar')),
          ],
        ),
      ),
    );
    if (ok != true || chosen == null) return;
    try {
      await state.api.post('/market/listings', body: {
        'item_id': chosen!['id'],
        if (price.text.trim().isNotEmpty) 'price': price.text.trim().replaceAll(',', '.'),
        'accepts_trades': trades,
        if (desc.text.trim().isNotEmpty) 'description': desc.text.trim(),
      });
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _offer(Map<String, dynamic> listing) async {
    final state = context.read<AppState>();
    if (!state.loggedIn) {
      showError(context, 'Inicia sesión para hacer ofertas');
      return;
    }
    final amount = TextEditingController(text: listing['price']?.toString() ?? '');
    final msg = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Hacer una oferta'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
            controller: amount,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'Importe (€)'),
          ),
          TextField(controller: msg, decoration: const InputDecoration(labelText: 'Mensaje')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Enviar')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await state.api.post('/market/listings/${listing['id']}/offers', body: {
        if (amount.text.trim().isNotEmpty) 'amount': amount.text.trim().replaceAll(',', '.'),
        if (msg.text.trim().isNotEmpty) 'message': msg.text.trim(),
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Oferta enviada')));
      }
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _manageOffers(Map<String, dynamic> listing) async {
    final api = context.read<AppState>().api;
    try {
      final offers =
          List<Map<String, dynamic>>.from(await api.get('/market/listings/${listing['id']}/offers'));
      if (!mounted) return;
      await showModalBottomSheet(
        context: context,
        showDragHandle: true,
        builder: (ctx) => ListView(padding: const EdgeInsets.all(16), children: [
          Text('Ofertas recibidas (${offers.length})', style: Theme.of(context).textTheme.titleMedium),
          if (offers.isEmpty) const Text('Todavía nadie ha ofertado.'),
          for (final o in offers)
            ListTile(
              title: Text(o['amount'] != null ? euro(o['amount']) : 'Intercambio'),
              subtitle: Text('${o['message'] ?? ''} · ${kOfferStatus[o['status']] ?? o['status']}'),
              trailing: o['status'] == 'pending'
                  ? Row(mainAxisSize: MainAxisSize.min, children: [
                      IconButton(
                          icon: const Icon(Icons.check, color: Colors.green),
                          onPressed: () async {
                            await api.post('/market/offers/${o['id']}/accept');
                            if (ctx.mounted) Navigator.pop(ctx);
                          }),
                      IconButton(
                          icon: const Icon(Icons.close, color: Colors.red),
                          onPressed: () async {
                            await api.post('/market/offers/${o['id']}/reject');
                            if (ctx.mounted) Navigator.pop(ctx);
                          }),
                    ])
                  : null,
            ),
          TextButton(
              onPressed: () async {
                await api.delete('/market/listings/${listing['id']}');
                if (ctx.mounted) Navigator.pop(ctx);
              },
              child: const Text('Retirar anuncio')),
        ]),
      );
      await _load();
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> _rate(Map<String, dynamic> offer) async {
    final api = context.read<AppState>().api;
    int stars = 5;
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setD) => AlertDialog(
          title: const Text('Valorar al vendedor'),
          content: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            for (var i = 1; i <= 5; i++)
              IconButton(
                  icon: Icon(i <= stars ? Icons.star : Icons.star_border, color: Colors.amber),
                  onPressed: () => setD(() => stars = i)),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancelar')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Valorar')),
          ],
        ),
      ),
    );
    if (ok != true) return;
    try {
      await api.post('/market/offers/${offer['id']}/rate', body: {'stars': stars});
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Gracias por valorar')));
      }
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final state = context.watch<AppState>();
    final me = state.user?['id'];
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return ErrorBox(_error!, onRetry: _load);
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(padding: const EdgeInsets.all(12), children: [
        Row(children: [
          const Expanded(
            child: Text(
              'Sin comisiones. Solo piezas verificadas con foto; cada venta queda en la trazabilidad de la moneda.',
              style: TextStyle(fontSize: 12),
            ),
          ),
          FilledButton.icon(onPressed: _publish, icon: const Icon(Icons.sell), label: const Text('Vender')),
        ]),
        if (_myOffers.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text('Mis ofertas', style: Theme.of(context).textTheme.titleMedium),
          for (final o in _myOffers)
            ListTile(
              dense: true,
              leading: const Icon(Icons.local_offer),
              title: Text(o['amount'] != null ? euro(o['amount']) : 'Intercambio'),
              subtitle: Text(kOfferStatus[o['status']] ?? o['status']),
              trailing: o['status'] == 'accepted'
                  ? TextButton(onPressed: () => _rate(o), child: const Text('Valorar'))
                  : null,
            ),
        ],
        const SizedBox(height: 8),
        Text('Anuncios activos (${_listings.length})', style: Theme.of(context).textTheme.titleMedium),
        if (_listings.isEmpty)
          const Padding(
              padding: EdgeInsets.all(16),
              child: Text('No hay anuncios todavía. ¡Sé el primero en vender!')),
        for (final l in _listings)
          _ListingCard(
            listing: l,
            mine: l['seller']['id'] == me,
            onOpen: () => Navigator.of(context)
                .push(MaterialPageRoute(builder: (_) => CoinDetailScreen(typeId: l['type']['id']))),
            onAction: () => l['seller']['id'] == me ? _manageOffers(l) : _offer(l),
          ),
      ]),
    );
  }
}

class _ListingCard extends StatelessWidget {
  const _ListingCard(
      {required this.listing, required this.mine, required this.onOpen, required this.onAction});
  final Map<String, dynamic> listing;
  final bool mine;
  final VoidCallback onOpen, onAction;

  @override
  Widget build(BuildContext context) {
    final api = context.read<AppState>().api;
    final seller = Map<String, dynamic>.from(listing['seller']);
    final rep = Map<String, dynamic>.from(seller['reputation'] ?? {});
    final issue = Map<String, dynamic>.from(listing['issue']);
    return Card(
      child: Column(children: [
        TypeTile(
          api: api,
          type: Map<String, dynamic>.from(listing['type']),
          onTap: onOpen,
          trailing: Text(listing['price'] != null ? euro(listing['price']) : 'Cambio',
              style: Theme.of(context).textTheme.titleMedium),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 8, 6),
          child: Row(children: [
            Expanded(
              child: Wrap(children: [
                Chip2(kGradeLabel[listing['grade']] ?? listing['grade']),
                Chip2(kFinishLabel[issue['finish']] ?? issue['finish']),
                if (listing['accepts_trades'] == true) const Chip2('acepta cambios'),
                Chip2('${seller['display_name']} · ★ ${rep['average_stars'] ?? '—'} '
                    '(${rep['ratings'] ?? 0} val., ${rep['completed_transactions'] ?? 0} op.)'),
              ]),
            ),
            TextButton(onPressed: onAction, child: Text(mine ? 'Gestionar' : 'Ofertar')),
          ]),
        ),
        if (listing['description'] != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
            child: Align(
                alignment: Alignment.centerLeft,
                child: Text(listing['description'], style: const TextStyle(fontSize: 12))),
          ),
      ]),
    );
  }
}
