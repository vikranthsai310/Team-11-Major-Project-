//// Datum and redeemer types shared by the order and pool validators.

use aiken/crypto.{VerificationKeyHash}
use cardano/address.{Address}
use cardano/assets.{AssetName, PolicyId}

/// Which way an order swaps. Asset A is always lovelace; asset B is the pool token.
pub type Direction {
  AtoB
  BtoA
}

/// An order locked at the order script by a user's wallet.
pub type OrderDatum {
  /// May cancel the order and reclaim its funds at any time (T-O1).
  owner: VerificationKeyHash,
  /// Where the swapped funds must be paid (T-O2).
  return_address: Address,
  direction: Direction,
  /// Units of the input asset to swap.
  amount_in: Int,
  /// The slippage floor: fewest units of the output asset the user accepts (T-O2).
  min_out: Int,
  /// The batcher's service margin in lovelace, on top of the fee share (T-O5).
  margin: Int,
}

pub type OrderAction {
  /// The batcher executes the order inside a batch.
  Execute
  /// The owner reclaims an unbatched order.
  Cancel
}

/// The pool's identity and parameters. Reserves are read from the UTxO's value.
pub type PoolDatum {
  token_policy: PolicyId,
  token_name: AssetName,
  /// Pool identity NFT, which must be carried through every batch (T-O4).
  nft_policy: PolicyId,
  nft_name: AssetName,
  /// Swap fee in basis points, retained by the pool.
  fee_bps: Int,
}
