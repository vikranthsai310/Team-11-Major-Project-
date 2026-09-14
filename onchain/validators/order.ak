//// Order validator (P7-2, P7-3).
////
//// A user locks funds here with an `OrderDatum`. The batcher is untrusted for
//// correctness: whatever it builds, a batch that short-changes a user fails
//// validation (T-O2), and only the authorised batcher key can execute at all
//// (T-O3). The user can always walk away with their funds (T-O1).
////
//// The batcher fee is pass-through (ADR-006): a user is charged their share of
//// the actual network fee, `fee / n`, plus a fixed margin, never a flat amount.
//// That is what makes amortization reach the user rather than the operator (T-O5).

use aiken/collection/list
use aiken/crypto.{VerificationKeyHash}
use cardano/address
use cardano/assets.{AssetName, PolicyId}
use cardano/transaction.{
  InlineDatum, Input, NoDatum, Output, OutputReference, Transaction,
}
use dex/types.{AtoB, BtoA, Cancel, Execute, OrderAction, OrderDatum}

validator order(
  batcher: VerificationKeyHash,
  token_policy: PolicyId,
  token_name: AssetName,
) {
  spend(
    datum: Option<OrderDatum>,
    redeemer: OrderAction,
    own_ref: OutputReference,
    self: Transaction,
  ) {
    expect Some(request) = datum
    when redeemer is {
      // T-O1: the owner may always reclaim an unbatched order.
      Cancel -> list.has(self.extra_signatories, request.owner)

      Execute -> {
        expect Some(own_input) = transaction.find_input(self.inputs, own_ref)
        let own_credential = own_input.output.address.payment_credential

        // n is the number of orders this batch executes: every input at this
        // script. The fee share falls as n grows — the amortization, passed on.
        let n = list.count(
          self.inputs,
          fn(input) {
            input.output.address.payment_credential == own_credential
          },
        )
        let charge = self.fee / n + request.margin

        // The payout is tagged with this order's own reference, so one output
        // cannot be counted as the payout for two orders (double satisfaction).
        let tag: Data = own_ref
        expect Some(payout) = list.find(
          self.outputs,
          fn(output) {
            output.address == request.return_address && output.datum == InlineDatum(
              tag,
            )
          },
        )

        let deposit = assets.lovelace_of(own_input.output.value)
        let paid_lovelace = assets.lovelace_of(payout.value)
        let paid_token = assets.quantity_of(
          payout.value,
          token_policy,
          token_name,
        )

        // T-O2 (slippage floor) and T-O5 (at most fee/n + margin kept back).
        let user_made_whole = when request.direction is {
          AtoB ->
            paid_token >= request.min_out && paid_lovelace >= deposit - request.amount_in - charge
          BtoA -> paid_lovelace >= deposit + request.min_out - charge
        }

        and {
          // T-O3: only the authorised batcher executes.
          list.has(self.extra_signatories, batcher),
          user_made_whole,
        }
      }
    }
  }

  else(_) {
    fail
  }
}

// --- Tests: T-O1, T-O2, T-O3, T-O5 -------------------------------------------

const batcher_key: VerificationKeyHash =
  #"b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0"

const owner_key: VerificationKeyHash =
  #"0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a"

const stranger_key: VerificationKeyHash =
  #"5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e"

const test_policy: PolicyId =
  #"c0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0"

const test_token: AssetName = "TEAM11"

const order_script = #"0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d0d"

const fee = 400_000

const margin = 1_000_000

fn ref(index: Int) -> OutputReference {
  OutputReference {
    transaction_id: #"1111111111111111111111111111111111111111111111111111111111111111",
    output_index: index,
  }
}

fn sell_ada() -> OrderDatum {
  OrderDatum {
    owner: owner_key,
    return_address: address.from_verification_key(owner_key),
    direction: AtoB,
    amount_in: 10_000_000,
    min_out: 9_800,
    margin,
  }
}

fn order_input(index: Int, lovelace: Int) -> Input {
  Input {
    output_reference: ref(index),
    output: Output {
      address: address.from_script(order_script),
      value: assets.from_lovelace(lovelace),
      datum: NoDatum,
      reference_script: None,
    },
  }
}

fn payout(for_index: Int, lovelace: Int, tokens: Int) -> Output {
  let tag: Data = ref(for_index)
  Output {
    address: address.from_verification_key(owner_key),
    value: assets.from_lovelace(lovelace)
      |> assets.add(test_policy, test_token, tokens),
    datum: InlineDatum(tag),
    reference_script: None,
  }
}

fn batch(inputs: List<Input>, outputs: List<Output>, signers) -> Transaction {
  Transaction {
    ..transaction.placeholder,
    inputs,
    outputs,
    extra_signatories: signers,
    fee,
  }
}

/// A one-order batch paying exactly what the datum allows: deposit 15 ADA,
/// 10 ADA swapped, 0.4 ADA fee share and 1 ADA margin kept back.
fn exact_single_batch(tokens: Int, lovelace: Int, signers) -> Transaction {
  batch([order_input(0, 15_000_000)], [payout(0, lovelace, tokens)], signers)
}

fn run(datum: OrderDatum, action: OrderAction, tx: Transaction) -> Bool {
  order.spend(
    batcher_key,
    test_policy,
    test_token,
    Some(datum),
    action,
    ref(0),
    tx,
  )
}

test t_o1_owner_can_cancel() {
  run(sell_ada(), Cancel, batch([order_input(0, 15_000_000)], [], [owner_key]))
}

test t_o1_nobody_else_can_cancel() {
  !run(
    sell_ada(),
    Cancel,
    batch([order_input(0, 15_000_000)], [], [batcher_key, stranger_key]),
  )
}

test executes_when_the_user_is_paid_in_full() {
  run(sell_ada(), Execute, exact_single_batch(9_800, 3_600_000, [batcher_key]))
}

test t_o2_below_the_slippage_floor_fails() {
  !run(sell_ada(), Execute, exact_single_batch(9_799, 3_600_000, [batcher_key]))
}

test t_o2_paying_someone_else_fails() fail {
  let tag: Data = ref(0)
  let elsewhere = Output {
    address: address.from_verification_key(stranger_key),
    value: assets.from_lovelace(3_600_000)
      |> assets.add(test_policy, test_token, 9_800),
    datum: InlineDatum(tag),
    reference_script: None,
  }
  run(
    sell_ada(),
    Execute,
    batch([order_input(0, 15_000_000)], [elsewhere], [batcher_key]),
  )
}

test t_o3_unauthorised_batcher_fails() {
  !run(
    sell_ada(),
    Execute,
    exact_single_batch(9_800, 3_600_000, [stranger_key]),
  )
}

test t_o5_charging_one_lovelace_over_the_fee_share_fails() {
  !run(sell_ada(), Execute, exact_single_batch(9_800, 3_599_999, [batcher_key]))
}

test t_o5_fee_share_falls_with_batch_size() {
  // Two orders share the 0.4 ADA fee, so each may be charged only 0.2 ADA plus
  // margin: the payout must be 3.8 ADA, and 3.6 ADA — fine for n = 1 — now fails.
  let two_orders = [order_input(0, 15_000_000), order_input(1, 15_000_000)]
  let fair = batch(two_orders, [payout(0, 3_800_000, 9_800)], [batcher_key])
  let overcharged = batch(
    two_orders,
    [payout(0, 3_600_000, 9_800)],
    [batcher_key],
  )
  run(sell_ada(), Execute, fair) && !run(sell_ada(), Execute, overcharged)
}

test one_payout_cannot_satisfy_two_orders() fail {
  // The only payout is tagged for order 1, so order 0 has none.
  run(
    sell_ada(),
    Execute,
    batch(
      [order_input(0, 15_000_000), order_input(1, 15_000_000)],
      [payout(1, 3_800_000, 9_800)],
      [batcher_key],
    ),
  )
}

test buy_ada_order_is_paid_its_lovelace() {
  let buy = OrderDatum {
    ..sell_ada(),
    direction: BtoA,
    amount_in: 10_000,
    min_out: 9_000_000,
  }
  // Deposit 5 ADA; receives at least 9 ADA; 1.4 ADA kept back => 12.6 ADA.
  let tx = batch(
    [order_input(0, 5_000_000)],
    [payout(0, 12_600_000, 0)],
    [batcher_key],
  )
  let short = batch(
    [order_input(0, 5_000_000)],
    [payout(0, 12_599_999, 0)],
    [batcher_key],
  )
  run(buy, Execute, tx) && !run(buy, Execute, short)
}
