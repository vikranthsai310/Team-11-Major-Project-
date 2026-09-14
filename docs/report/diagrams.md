# Report diagrams (P6-12)

The eight diagrams `16-REPORT-OUTLINE.md` §5.10 asks for, drawn from the code as
built rather than from the original design. Where the implementation diverged
from the specification, the diagram follows the implementation and says so.

Mermaid sources render directly on GitHub and in most Markdown viewers, and can be
exported to PNG for a Word report.

---

## 1 · Use case

The swap user never interacts with the batcher. The two are coupled only through
order UTXOs on chain — the reason there is no frontend.

```mermaid
flowchart LR
    user(["Swap user"])
    operator(["Batcher operator"])
    researcher(["Researcher / evaluator"])

    subgraph chain["Cardano (preprod)"]
        place["Place order<br/>(any CIP-30 wallet)"]
        cancel["Cancel unbatched order"]
        receive["Receive swapped tokens"]
    end

    subgraph batcher["Off-chain batcher (this system)"]
        run["Run batcher daemon"]
        decide["Decide WAIT / SUBMIT(n)"]
        submit["Build and submit batch"]
    end

    subgraph research["Research mode"]
        collect["Collect D1"]
        simulate["Replay episodes"]
        evaluate["Evaluate policies"]
    end

    user --> place
    user --> cancel
    receive --> user
    operator --> run
    run --> decide --> submit
    submit -. "spends order UTXOs" .-> receive
    place -. "order UTXO scanned" .-> decide
    researcher --> collect --> simulate --> evaluate
```

---

## 2 · Class

The interfaces that make the comparison honest: every policy sees the same
`Observation` and returns the same `Action`, so the simulator cannot tell a static
rule from a learned agent.

```mermaid
classDiagram
    class Policy {
        <<Protocol>>
        +name: str
        +decide(obs: Observation) Action
        +observe_outcome(outcome: Outcome)
    }
    class Observation {
        <<frozen>>
        +slot: int
        +queue_depth: int
        +oldest_wait: int
        +queue_sizes / queue_mem / queue_steps
        +fill_hat: tuple
        +pool_locked: bool
        +gate_a_max_n: int
    }
    class Action {
        <<frozen>>
        +submit: bool
        +n: int
    }
    class Outcome {
        <<frozen>>
        +included: bool
        +slots_to_confirm: int
        +fee_lovelace: int
    }
    class Order {
        <<frozen>>
        +order_id: str
        +arrival_slot: int
        +size_bytes / mem_exunits / step_exunits
        +ttl_slot: int
    }
    class OrderQueue {
        +admit(orders)
        +take(n) list~Order~
        +give_back(orders)
        +evict_expired(slot)
    }
    class InFlight {
        +orders: list~Order~
        +ttl_slot: int
        +size / mem / steps / fee
    }

    Policy ..> Observation : reads
    Policy ..> Action : returns
    Policy ..> Outcome : learns from
    OrderQueue o-- Order
    InFlight o-- Order

    Policy <|.. FixedSize : E1
    Policy <|.. FixedInterval : E2
    Policy <|.. Greedy : E3
    Policy <|.. Null
    Policy <|.. ConstrainedOptimizer : P2
    ConstrainedOptimizer <|-- OracleOptimizer
```

P3 is not a `Policy` subclass: the DQN agent acts through `BatchingEnv`, the
Gymnasium wrapper around the same event loop, and is scored through the same
metrics path.

---

## 3 · Sequence

One order from placement to settlement.

```mermaid
sequenceDiagram
    actor User
    participant Chain as Cardano chain
    participant M1 as M1 Collector
    participant M2 as M2 Forecaster
    participant M3 as M3 Queue
    participant M4 as M4 Policy
    participant M5 as M5 Builder

    User->>Chain: lock funds at order address (datum: terms, min_out)
    Chain-->>M3: order UTXO discovered
    Chain-->>M1: new block (size, slot, tx count)
    M1->>M2: features up to this block
    M2-->>M4: fill_hat t+1..t+3
    M3-->>M4: queue depth, oldest wait, per-order costs
    M4->>M4: environment masks WAIT past D_MAX, clamps n to Gate A
    M4->>M5: SUBMIT(n)
    M5->>M5: re-check Gate A (raises, never truncates)
    M5->>Chain: batch tx spends n orders + pool UTXO
    Note over Chain,M5: pool locked — no further decision until resolved
    Chain-->>M5: included in a block with room (Gate B)
    Chain-->>User: swapped tokens at return address
```

---

## 4 · Activity — the control loop, one block

The early exit while the pool is locked is the mechanism the project studies:
while a batch is in flight, **no decision exists**.

```mermaid
flowchart TD
    start([Block arrives]) --> admit[Admit arrivals<br/>evict expired orders]
    admit --> locked{Batch in flight?}

    locked -- no --> forecast[Forecast fill_hat]
    locked -- yes --> fits{Gate B holds<br/>for this block?}

    fits -- yes --> settle[Settle orders<br/>unlock pool]
    fits -- no --> ttl{TTL passed?}
    ttl -- yes --> expire[Return orders to queue<br/>at original age · unlock]
    ttl -- no --> hol[Head-of-line wait<br/>log, no decision]
    hol --> done([Next block])

    settle --> forecast
    expire --> forecast
    forecast --> observe[Build Observation<br/>gate_a_max_n from queue]
    observe --> decide[Policy.decide]
    decide --> enforce[Environment enforces:<br/>clamp n to Gate A · force SUBMIT past D_MAX]
    enforce --> act{SUBMIT?}
    act -- yes --> take[Take Q 0..n FIFO<br/>build in-flight batch · lock pool]
    act -- no --> log[Log decision]
    take --> log
    log --> done
```

---

## 5 · Data flow, level 0

```mermaid
flowchart LR
    koios[/"Koios API<br/>(public mainnet)"/]
    wallets[/"User wallets"/]
    chain[/"Cardano preprod"/]
    batcher(("Adaptive<br/>batcher"))
    report[/"Report · figures · tables"/]

    koios -- block statistics --> batcher
    wallets -- orders --> chain
    chain -- order UTXOs --> batcher
    batcher -- batch transactions --> chain
    batcher -- metrics, manifests --> report
```

---

## 6 · Data flow, level 1

```mermaid
flowchart TB
    koios[/"Koios"/]

    subgraph processes["Processes"]
        M1["M1 Collector"]
        M2["M2 Forecaster"]
        M3["M3 Queue"]
        M4["M4 Policy"]
        M5["M5 Builder / Estimator"]
        M6["M6 Simulator"]
    end

    D1[("D1 Block history<br/>388,781 blocks")]
    D2[("D2 Order stream<br/>generated")]
    D3[("D3 Decision log")]
    D4[("D4 Preprod log")]

    koios --> M1 --> D1
    D1 --> M2
    D1 --> M6
    D2 --> M3
    M2 -- fill_hat --> M4
    M3 -- queue state --> M4
    M4 -- WAIT / SUBMIT n --> M5
    M5 -- outcome --> M4
    M6 -. drives offline .-> M2
    M6 -. drives offline .-> M4
    M6 --> D3
    M5 -. live mode only .-> D4
```

---

## 7 · State — the pool lock

The diagram the outline singles out. A submitted batch holds the pool UTXO; every
order that arrives meanwhile waits behind it. Note what is **absent**: there is no
"rejected" or "bounced" state. A batch that does not fit a block stays in the
mempool and is retried against the next one (ADR-004).

```mermaid
stateDiagram-v2
    [*] --> Idle

    Idle --> Idle : block · WAIT
    Idle --> InFlight : block · SUBMIT(n) · pool locked
    Idle --> InFlight : oldest_wait ≥ D_MAX · SUBMIT forced

    InFlight --> InFlight : no room (Gate B fails) · head-of-line wait
    InFlight --> Confirmed : block with room (Gate B holds)
    InFlight --> Expired : TTL passes before inclusion

    Confirmed --> Idle : orders settled · pool unlocked
    Confirmed --> RolledBack : short fork (p = 0.0005 / block)
    RolledBack --> Idle : orders returned at original age
    Expired --> Idle : orders returned at original age

    note right of InFlight
        Measured cost of this state:
        D_MAX bounds the decision, not the wait —
        overshoot up to 114 slots observed (Phase 2).
    end note
```

*Implementation note.* The simulator models rollback; the Gym environment P3 trains
in does not. It is a small asymmetry (p = 0.0005 per block) and is recorded in the
Phase 6 evaluation manifest.

---

## 8 · Deployment

```mermaid
flowchart TB
    subgraph research["Research mode — produces every reported result"]
        laptop["Laptop · single Python process<br/>no network, no GPU"]
        disk[("D1 parquet · models<br/>experiments/")]
        laptop <--> disk
    end

    subgraph live["Live mode — optional Phase 7 demo"]
        daemon["Batcher daemon"]
        keys[("~/.cardano-batcher/<br/>signing keys, outside repo")]
        daemon --- keys
    end

    koios["Koios / Blockfrost<br/>HTTPS"]
    preprod["Cardano preprod"]

    laptop -- one-off collection --> koios
    daemon -- chain queries --> koios
    daemon -- submit batch --> preprod
    koios --- preprod
```

No inbound ports, no database server, no user-facing endpoint in either mode.
