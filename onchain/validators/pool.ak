//// Pool validator (P7-4).
////
//// One liquidity pool as a single UTxO holding lovelace (asset A) and one token
//// (asset B), identified by an NFT. It is the single-writer resource the whole
//// project is about: each batch spends it and recreates it, so no second batch
//// can be built until this one confirms.
////
//// T-O4: after fees, x·y must be preserved or increased. The fee is charged on
//// the net inflow of each asset, so a batch can never extract value from the
//// pool, whatever mix of orders it nets together.

use aiken/collection/list
use aiken/crypto.{VerificationKeyHash}
use cardano/address
use cardano/assets
use cardano/transaction.{
  InlineDatum, Input, NoDatum, Output, OutputReference, Transaction,
}
use dex/types.{PoolDatum}

const bps = 10_000

/// The fee-adjusted constant-product check, exposed so tests can probe it.
pub fn invariant_holds(
  x: Int,
  y: Int,
  x_new: Int,
  y_new: Int,
  fee_bps: Int,
) -> Bool {
  let inflow_x = if x_new > x {
    x_new - x
  } else {
    0
  }
  let inflow_y = if y_new > y {
    y_new - y
  } else {
    0
  }
  let adjusted_x = x_new * bps - inflow_x * fee_bps
  let adjusted_y = y_new * bps - inflow_y * fee_bps
  adjusted_x * adjusted_y >= x * y * bps * bps
}

validator pool(batcher: VerificationKeyHash) {
  spend(
    datum: Option<PoolDatum>,
    _redeemer: Data,
    own_ref: OutputReference,
    self: Transaction,
  ) {
    expect Some(params) = datum
    expect Some(own_input) = transaction.find_input(self.inputs, own_ref)
    let old = own_input.output

    let carries_nft = fn(output: Output) {
      assets.quantity_of(output.value, params.nft_policy, params.nft_name) == 1
    }

    // Exactly one continuing pool output: same address, still holding the NFT.
    expect [new] = list.filter(
      self.outputs,
      fn(output) { output.address == old.address && carries_nft(output) },
    )

    let unchanged_params: Data = params
    let x = assets.lovelace_of(old.value)
    let y = assets.quantity_of(
      old.value,
      params.token_policy,
      params.token_name,
    )
    let x_new = assets.lovelace_of(new.value)
    let y_new = assets.quantity_of(
      new.value,
      params.token_policy,
      params.token_name,
    )

    and {
      list.has(self.extra_signatories, batcher),
      carries_nft(old),
      new.datum == InlineDatum(unchanged_params),
      x_new > 0,
      y_new > 0,
      invariant_holds(x, y, x_new, y_new, params.fee_bps),
    }
  }

  else(_) {
    fail
  }
}

// --- Tests: T-O4 ----------------------------------------------------------------

const batcher_key: VerificationKeyHash =
  #"b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0"

const stranger_key: VerificationKeyHash =
  #"5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e5e"

const pool_script = #"90909090909090909090909090909090909090909090909090909090"

fn params() -> PoolDatum {
  PoolDatum {
    token_policy: #"c0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0ffeec0",
    token_name: "TEAM11",
    nft_policy: #"a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1a1",
    nft_name: "POOL",
    fee_bps: 30,
  }
}

fn pool_ref() -> OutputReference {
  OutputReference {
    transaction_id: #"2222222222222222222222222222222222222222222222222222222222222222",
    output_index: 0,
  }
}

fn pool_output(
  lovelace: Int,
  tokens: Int,
  with_nft: Bool,
  datum: PoolDatum,
) -> Output {
  let p = params()
  let d: Data = datum
  let value = assets.from_lovelace(lovelace)
    |> assets.add(p.token_policy, p.token_name, tokens)
  Output {
    address: address.from_script(pool_script),
    value: if with_nft {
      assets.add(value, p.nft_policy, p.nft_name, 1)
    } else {
      value
    },
    datum: InlineDatum(d),
    reference_script: None,
  }
}

/// Spend a pool of 1,000 ADA and 1,000,000 tokens into `new_output`.
fn swap(new_output: Output, signers) -> Bool {
  let tx = Transaction {
    ..transaction.placeholder,
    inputs: [
      Input {
        output_reference: pool_ref(),
        output: pool_output(1_000_000_000, 1_000_000, True, params()),
      },
    ],
    outputs: [new_output],
    extra_signatories: signers,
  }
  pool.spend(batcher_key, Some(params()), NoDatum, pool_ref(), tx)
}

fn after(lovelace: Int, tokens: Int) -> Output {
  pool_output(lovelace, tokens, True, params())
}

test t_o4_a_fair_swap_after_fees_is_accepted() {
  // 10 ADA in at 30 bps: the constant-product quote is 9,871 tokens out.
  swap(after(1_010_000_000, 990_129), [batcher_key])
}

test t_o4_ignoring_the_fee_is_rejected() {
  // The no-fee quote, 9,900 tokens, takes the fee out of the pool: rejected.
  !swap(after(1_010_000_000, 990_100), [batcher_key])
}

test t_o4_invariant_never_decreases_for_accepted_batches() {
  and {
    invariant_holds(1_000_000_000, 1_000_000, 1_010_000_000, 990_129, 30),
    !invariant_holds(1_000_000_000, 1_000_000, 1_010_000_000, 990_100, 30),
    // Adding liquidity to both sides can only help.
    invariant_holds(1_000_000_000, 1_000_000, 1_100_000_000, 1_100_000, 30),
    // Removing from both sides is extraction.
    !invariant_holds(1_000_000_000, 1_000_000, 999_000_000, 999_000, 30),
  }
}

test t_o4_the_pool_nft_must_carry_through() fail {
  swap(pool_output(1_010_000_000, 990_129, False, params()), [batcher_key])
}

test t_o4_pool_parameters_cannot_be_rewritten() {
  let greedier = PoolDatum { ..params(), fee_bps: 0 }
  !swap(pool_output(1_010_000_000, 990_129, True, greedier), [batcher_key])
}

test only_the_batcher_may_spend_the_pool() {
  !swap(after(1_010_000_000, 990_129), [stranger_key])
}
