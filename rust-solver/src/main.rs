//! Clue-only symmetric exact cover. Geometry is u128; cell data is flat.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashSet, VecDeque};
use std::io::{BufReader, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
const INF: i64 = i64::MAX / 8;
fn bits(mut mask: u128) -> impl Iterator<Item = usize> {
    std::iter::from_fn(move || {
        if mask == 0 {
            None
        } else {
            let i = mask.trailing_zeros() as usize;
            mask &= mask - 1;
            Some(i)
        }
    })
}
#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
struct Shape {
    mask: u128,
    cap: Option<usize>,
    area: i64,
}
struct Board {
    size: usize,
    n: usize,
    full: u128,
    adj: Vec<u128>,
    clues: Vec<Option<i64>>,
    low: Vec<i64>,
    forced: u128,
    zeros: u128,
    groups: Vec<u128>,
}
impl Board {
    fn new(clues: Vec<Option<i64>>, size: usize) -> Result<Self, String> {
        if !(1..=11).contains(&size)
            || clues.len() != size * size
            || clues
                .iter()
                .flatten()
                .any(|&v| !(0..=1_000_000_000).contains(&v))
        {
            return Err(
                "Expected square board size 1..11 and nonnegative integer clues <= 1000000000"
                    .into(),
            );
        }
        let n = size * size;
        let mut b = Self {
            size,
            n,
            full: (1u128 << n) - 1,
            adj: vec![0; n],
            clues,
            low: vec![1; n],
            forced: 0,
            zeros: 0,
            groups: vec![],
        };
        for i in 0..n {
            let (r, c) = (i / size, i % size);
            for (dr, dc) in [(-1, 0), (1, 0), (0, -1), (0, 1)] {
                let (rr, cc) = (r as i32 + dr, c as i32 + dc);
                if rr >= 0 && cc >= 0 && rr < size as i32 && cc < size as i32 {
                    b.adj[i] |= 1u128 << (rr as usize * size + cc as usize);
                }
            }
        }
        for i in 0..n {
            if let Some(v) = b.clues[i] {
                if v > 0 {
                    b.low[i] = b.low[i].max(2)
                } else {
                    b.zeros |= 1u128 << i;
                }
                for j in bits(b.adj[i]) {
                    if let Some(w) = b.clues[j] {
                        let d = (v - w).abs();
                        b.low[i] = b.low[i].max(d);
                        b.low[j] = b.low[j].max(d);
                    }
                }
            }
        }
        let allowed = (0..n)
            .filter(|&i| {
                b.low[i] == 1
                    && b.clues[i].unwrap_or(0) == 0
                    && bits(b.adj[i]).all(|j| b.clues[j].unwrap_or(0) <= 1)
            })
            .fold(0, |m, i| m | 1u128 << i);
        for i in 0..n {
            if b.clues[i] == Some(1) {
                let g = b.adj[i] & allowed;
                if g == 0 {
                    return Err("Clue 1 has no possible adjacent singleton".into());
                }
                b.groups.push(g);
                if g.count_ones() == 1 {
                    b.forced |= g;
                }
            }
        }
        for s in bits(b.forced) {
            for q in bits(b.adj[s]) {
                for p in bits(b.adj[q]) {
                    if let Some(v) = b.clues[p] {
                        if v > 1 {
                            b.low[q] = b.low[q].max(v - 1);
                            b.low[p] = b.low[p].max(v - 1);
                        }
                    }
                }
            }
        }
        for i in bits(b.zeros) {
            if b.low[i] % 2 == 0 {
                b.low[i] += 1;
            }
        }
        if b.low.iter().any(|&v| v > n as i64) {
            return Err("Required area exceeds board".into());
        }
        Ok(b)
    }
    fn neighbors(&self, mask: u128) -> u128 {
        bits(mask).fold(0, |m, i| m | self.adj[i])
    }
    fn connected(&self, mask: u128) -> bool {
        if mask == 0 {
            return false;
        }
        let mut reached = mask & mask.wrapping_neg();
        loop {
            let next = reached | (self.neighbors(reached) & mask);
            if next == reached {
                return reached == mask;
            }
            reached = next;
        }
    }
    fn envelope(&self, areas: &[i64], seeds: impl Iterator<Item = (usize, i64)>) -> Vec<i64> {
        let mut d = vec![INF; self.n];
        let mut q = BinaryHeap::new();
        for (i, v) in seeds {
            if v < d[i] {
                d[i] = v;
                q.push(Reverse((v, i)));
            }
        }
        while let Some(Reverse((v, i))) = q.pop() {
            if v != d[i] {
                continue;
            }
            for j in bits(self.adj[i]) {
                let x = v + areas[i].min(areas[j]);
                if x < d[j] {
                    d[j] = x;
                    q.push(Reverse((x, j)));
                }
            }
        }
        d
    }
    fn shape(&self, mask: u128) -> Option<Shape> {
        let cells: Vec<_> = bits(mask).collect();
        if cells.is_empty() {
            return None;
        }
        let minr = cells.iter().map(|i| i / self.size).min()? as i32;
        let maxr = cells.iter().map(|i| i / self.size).max()? as i32;
        let minc = cells.iter().map(|i| i % self.size).min()? as i32;
        let maxc = cells.iter().map(|i| i % self.size).max()? as i32;
        let mut symmetric = false;
        let mut common = None;
        let mut valid_cap = true;
        for op in 0..7 {
            let mut mapped = 0u128;
            let mut fixed = 0u128;
            let mut valid = true;
            for &i in &cells {
                let (r, c) = ((i / self.size) as i32, (i % self.size) as i32);
                let (rr, cc) = match op {
                    0 => (minr + maxc - c, minc + r - minr),
                    1 => (minr + maxr - r, minc + maxc - c),
                    2 => (minr + c - minc, minc + maxr - r),
                    3 => (minr + maxr - r, c),
                    4 => (r, minc + maxc - c),
                    5 => (minr + c - minc, minc + r - minr),
                    _ => (minr + maxc - c, minc + maxr - r),
                };
                if rr < 0 || cc < 0 || rr >= self.size as i32 || cc >= self.size as i32 {
                    valid = false;
                    break;
                }
                let j = rr as usize * self.size + cc as usize;
                mapped |= 1u128 << j;
                if j == i {
                    fixed |= 1u128 << i;
                }
            }
            if valid && mapped == mask {
                symmetric = true;
                if fixed.count_ones() != 1 {
                    valid_cap = false
                } else {
                    let k = fixed.trailing_zeros() as usize;
                    if common.is_some_and(|old| old != k) {
                        valid_cap = false
                    }
                    common = Some(k);
                }
            }
        }
        symmetric.then_some(Shape {
            mask,
            cap: if valid_cap { common } else { None },
            area: cells.len() as i64,
        })
    }
    fn extendable(&self, m: u128) -> bool {
        m & self.forced == 0
            && (m & self.zeros).count_ones() <= 1
            && !self.groups.iter().any(|g| m & g == *g)
            && !(0..self.n).any(|i| {
                self.clues[i].is_some_and(|v| v > 0 && v < (m.count_ones() as i64))
                    && m & (self.adj[i] | 1u128 << i) == (self.adj[i] | 1u128 << i)
            })
    }
    fn assess(&self, m: u128, forbidden: u128) -> Option<Shape> {
        let a = m.count_ones() as i64;
        if bits(m).any(|i| self.low[i] > a)
            || (a > 1 && (m & self.forced != 0 || self.groups.iter().any(|g| m & g == *g)))
            || !self.connected(m)
        {
            return None;
        }
        let s = self.shape(m)?;
        let capmask = s.cap.map_or(0, |i| 1u128 << i);
        if m & self.zeros & !capmask != 0 || capmask & forbidden != 0 {
            return None;
        }
        let mut lo = vec![INF; self.n];
        let mut hi = lo.clone();
        if let Some(c) = s.cap {
            lo[c] = 0;
            hi[c] = 0;
        }
        for i in bits(m) {
            for j in bits(self.adj[i] & !m) {
                lo[i] = lo[i].min(a.min(self.low[j]));
                if self.forced & (1u128 << j) != 0 {
                    hi[i] = hi[i].min(1)
                } else if self.zeros & (1u128 << j) != 0 {
                    hi[i] = hi[i].min(a)
                }
            }
        }
        for d in [&mut lo, &mut hi] {
            let mut q = BinaryHeap::new();
            for i in bits(m) {
                if d[i] < INF {
                    q.push(Reverse((d[i], i)));
                }
            }
            while let Some(Reverse((v, i))) = q.pop() {
                if v != d[i] {
                    continue;
                }
                for j in bits(self.adj[i] & m) {
                    if v + a < d[j] {
                        d[j] = v + a;
                        q.push(Reverse((d[j], j)));
                    }
                }
            }
        }
        for i in bits(m) {
            if self.clues[i].is_some_and(|v| v < lo[i] || v > hi[i]) {
                return None;
            }
            for j in bits(self.adj[i] & !m) {
                if self.clues[j].is_some_and(|v| v > hi[i] + a) {
                    return None;
                }
            }
        }
        // Internal clue differences cannot exceed the cost of an internal path.
        for source in bits(m).filter(|&i| self.clues[i].is_some()) {
            let mut d = vec![INF; self.n];
            d[source] = 0;
            let mut q = VecDeque::from([source]);
            while let Some(i) = q.pop_front() {
                for j in bits(self.adj[i] & m) {
                    if d[j] == INF {
                        d[j] = d[i] + a;
                        q.push_back(j);
                    }
                }
            }
            for j in bits(m) {
                if let Some(v) = self.clues[j] {
                    if (self.clues[source].unwrap() - v).abs() > d[j] {
                        return None;
                    }
                }
            }
        }
        Some(s)
    }
}
#[derive(Serialize, Deserialize)]
struct Walker {
    orbits: Vec<u128>,
    stack: Vec<u128>,
    seen: HashSet<u128>,
}
#[cfg(test)]
fn generate(
    b: &Board,
    root: usize,
    limit: usize,
    deadline: Instant,
    node_limit: usize,
    forbidden: u128,
) -> (Vec<Shape>, bool) {
    let mut generator = Generator::new(b, root, limit);
    let mut out = vec![];
    for _ in 0..node_limit {
        if Instant::now() >= deadline || generator.walkers.is_empty() {
            break;
        }
        if let Some(s) = generator.step(b, forbidden) {
            out.push(s);
        }
    }
    (out, generator.walkers.is_empty())
}
#[derive(Serialize, Deserialize)]
struct Generator {
    root: usize,
    limit: usize,
    walkers: VecDeque<Walker>,
    seen: HashSet<u128>,
    visited: u64,
}
impl Generator {
    fn new(b: &Board, root: usize, limit: usize) -> Self {
        let mut transforms = vec![];
        let size = b.size as i32;
        for k in 0..2 * size - 1 {
            for op in 0..3 {
                transforms.push((op, k, 0));
            }
        }
        for k in -(size - 1)..size {
            transforms.push((3, k, 0));
        }
        for r in 0..2 * size - 1 {
            for c in 0..2 * size - 1 {
                transforms.push((4, r, c));
            }
        }
        let mut walkers = VecDeque::new();
        for (op, k, l) in transforms {
            let mut orbits = vec![0; b.n];
            for (i, orbit) in orbits.iter_mut().enumerate() {
                let (r, c) = ((i / b.size) as i32, (i % b.size) as i32);
                let (rr, cc) = match op {
                    0 => (k - r, c),
                    1 => (r, k - c),
                    2 => (k - c, k - r),
                    3 => (c + k, r - k),
                    _ => (k - r, l - c),
                };
                if rr >= 0 && cc >= 0 && rr < size && cc < size {
                    *orbit = (1u128 << i) | (1u128 << (rr as usize * b.size + cc as usize));
                }
            }
            let m = orbits[root];
            if m == 0 || m.count_ones() as usize > limit {
                continue;
            }
            let other = bits(m).find(|&i| i != root).unwrap_or(root);
            if (other / b.size).abs_diff(root / b.size) + (other % b.size).abs_diff(root % b.size)
                > limit - 1
            {
                continue;
            }
            walkers.push_back(Walker {
                orbits,
                stack: vec![m],
                seen: HashSet::from([m]),
            });
        }
        Self {
            root,
            limit,
            walkers,
            seen: HashSet::new(),
            visited: 0,
        }
    }
    fn step(&mut self, b: &Board, forbidden: u128) -> Option<Shape> {
        let mut w = self.walkers.pop_front()?;
        self.visited += 1;
        let mut found = None;
        let m = w.stack.pop()?;
        if self.seen.insert(m) {
            if let Some(s) = b.assess(m, forbidden) {
                found = Some(s);
            }
        }
        if b.extendable(m) {
            let mut children: Vec<_> = bits(b.neighbors(m) & !m)
                .filter_map(|i| {
                    let orbit = w.orbits[i];
                    (orbit != 0).then_some(m | orbit)
                })
                .collect();
            children.sort_unstable();
            children.dedup();
            for child in children {
                if child.count_ones() as usize <= self.limit && w.seen.insert(child) {
                    w.stack.push(child);
                }
            }
        }
        if !w.stack.is_empty() {
            self.walkers.push_back(w);
        }
        found
    }
}

fn support(b: &Board, s: Shape, low: &[i64], high: &[i64], lower: &[i64], upper: &[i64]) -> bool {
    for i in bits(s.mask) {
        let mut lo = lower[i];
        let mut hi = upper[i];
        if s.cap == Some(i) {
            if lo > 0 {
                return false;
            }
            hi = hi.min(0)
        } else {
            lo = lo.max(1)
        }
        let mut edges = vec![];
        for j in bits(b.adj[i]) {
            let inside = s.mask & (1u128 << j) != 0;
            let wl = if inside { s.area } else { s.area.min(low[j]) };
            let wh = if inside { s.area } else { s.area.min(high[j]) };
            let mut jl = lower[j];
            let mut jh = upper[j];
            if s.cap == Some(j) {
                jl = jl.max(0);
                jh = jh.min(0)
            } else if inside {
                jl = jl.max(1)
            }
            lo = lo.max(jl - wh);
            hi = hi.min(jh + wh);
            edges.push((jl, jh, wl, wh));
        }
        if lo > hi
            || (s.cap != Some(i)
                && !edges
                    .iter()
                    .any(|&(jl, jh, wl, wh)| lo.max(jl + wl) <= hi.min(jh + wh)))
        {
            return false;
        }
    }
    true
}
fn travel(
    b: &Board,
    pool: &[Shape],
    chosen: &[usize],
    domains: &[Vec<usize>],
    occupied: u128,
    max_area: usize,
) -> Option<HashSet<usize>> {
    let mut low = b.low.clone();
    let mut high = vec![max_area as i64; b.n];
    let mut possible = b.full;
    let mut certain = b.zeros | b.forced;
    for i in 0..b.n {
        if b.clues[i].unwrap_or(0) > 0 {
            possible &= !(1u128 << i);
        }
        if b.forced & (1u128 << i) != 0 {
            low[i] = 1;
            high[i] = 1;
        }
        if occupied & (1u128 << i) == 0 {
            if domains[i].is_empty() {
                return None;
            }
            low[i] = low[i].max(domains[i].iter().map(|&k| pool[k].area).min()?);
            high[i] = high[i].min(domains[i].iter().map(|&k| pool[k].area).max()?);
            if !domains[i].iter().any(|&k| pool[k].cap == Some(i)) {
                possible &= !(1u128 << i)
            }
            if domains[i].iter().all(|&k| pool[k].cap == Some(i)) {
                certain |= 1u128 << i;
            }
        }
    }
    for &k in chosen {
        let s = pool[k];
        let cm = s.cap.map_or(0, |i| 1u128 << i);
        if s.mask & certain & !cm != 0 || bits(s.mask).any(|i| s.area < low[i] || s.area > high[i])
        {
            return None;
        }
        for i in bits(s.mask) {
            low[i] = s.area;
            high[i] = s.area;
        }
        possible = (possible & !s.mask) | cm;
        certain |= cm;
    }
    if low.iter().zip(&high).any(|(a, z)| a > z) || certain & !possible != 0 {
        return None;
    }
    let upper = b.envelope(
        &high,
        b.clues
            .iter()
            .enumerate()
            .filter_map(|(i, &v)| v.map(|x| (i, x)))
            .chain(bits(certain).map(|i| (i, 0))),
    );
    if (0..b.n).any(|i| b.clues[i].is_some_and(|v| upper[i] < v)) {
        return None;
    }
    let negative = b.envelope(
        &high,
        b.clues
            .iter()
            .enumerate()
            .filter_map(|(i, &v)| v.map(|x| (i, -x))),
    );
    for (i, &value) in negative.iter().enumerate() {
        if value < 0 {
            possible &= !(1u128 << i);
        }
    }
    if possible == 0 || certain & !possible != 0 {
        return None;
    }
    let mut lower = b.envelope(&low, bits(possible).map(|i| (i, 0)));
    for i in 0..b.n {
        lower[i] = lower[i].max(-negative[i]);
        if lower[i] > upper[i] {
            return None;
        }
    }
    if chosen
        .iter()
        .any(|&k| !support(b, pool[k], &low, &high, &lower, &upper))
    {
        return None;
    }
    let active: HashSet<_> = domains.iter().flatten().copied().collect();
    Some(
        active
            .into_iter()
            .filter(|&k| !support(b, pool[k], &low, &high, &lower, &upper))
            .collect(),
    )
}
#[derive(Hash, PartialEq, Eq, Serialize, Deserialize)]
struct Signature {
    areas: Vec<(i64, u128)>,
    caps: u128,
}
fn signature(pool: &[Shape], chosen: &[usize]) -> Signature {
    let mut by_area = [0u128; 122];
    let mut caps = 0;
    for &k in chosen {
        let s = pool[k];
        by_area[s.area as usize] |= s.mask;
        if let Some(i) = s.cap {
            caps |= 1u128 << i;
        }
    }
    Signature {
        areas: by_area
            .iter()
            .enumerate()
            .filter(|(_, m)| **m != 0)
            .map(|(a, &m)| (a as i64, m))
            .collect(),
        caps,
    }
}
#[derive(Default, Serialize, Deserialize)]
struct Stats {
    nodes: usize,
    travel_prunes: usize,
    cover_prunes: usize,
    support_prunes: usize,
    equivalent_prunes: usize,
    rounds: usize,
    best: usize,
}
#[derive(Serialize, Deserialize)]
struct SearchState {
    // DFS worklist. A prefix is removed only after a whole search node finishes.
    pending: Vec<Vec<usize>>,
    expanded: HashSet<Signature>,
}
impl SearchState {
    fn new() -> Self {
        Self {
            pending: vec![vec![]],
            expanded: HashSet::new(),
        }
    }
    fn step(
        &mut self,
        b: &Board,
        pool: &[Shape],
        cover: &[Vec<usize>],
        max_area: usize,
        stats: &mut Stats,
    ) -> Option<Vec<usize>> {
        let chosen = self.pending.pop()?;
        let sig = signature(pool, &chosen);
        if !self.expanded.insert(sig) {
            stats.equivalent_prunes += 1;
            return None;
        }
        let occupied = chosen.iter().fold(0, |m, &k| m | pool[k].mask);
        stats.nodes += 1;
        let mut domains = vec![vec![]; b.n];
        for i in bits(b.full ^ occupied) {
            domains[i] = cover[i]
                .iter()
                .copied()
                .filter(|&k| pool[k].mask & occupied == 0)
                .collect();
            if domains[i].is_empty() {
                stats.cover_prunes += 1;
                return None;
            }
        }
        for _ in 0..3 {
            let Some(unsupported) = travel(b, pool, &chosen, &domains, occupied, max_area) else {
                stats.travel_prunes += 1;
                return None;
            };
            if unsupported.is_empty() {
                break;
            }
            stats.support_prunes += unsupported.len();
            for i in bits(b.full ^ occupied) {
                domains[i].retain(|k| !unsupported.contains(k));
                if domains[i].is_empty() {
                    stats.cover_prunes += 1;
                    return None;
                }
            }
        }
        stats.best = stats.best.max(occupied.count_ones() as usize);
        if occupied == b.full {
            return verify(b, pool, &chosen).then_some(chosen);
        }
        let root = bits(b.full ^ occupied)
            .min_by_key(|&i| {
                let mut sizes = 0u128;
                let mut max = 0;
                for &k in &domains[i] {
                    sizes |= 1u128 << pool[k].area;
                    max = max.max(pool[k].area);
                }
                (sizes.count_ones(), max, domains[i].len(), i)
            })
            .unwrap();
        domains[root].sort_unstable_by_key(|&k| (pool[k].area, k));
        for &k in domains[root].iter().rev() {
            let mut child = chosen.clone();
            child.push(k);
            self.pending.push(child);
        }
        None
    }
}
#[derive(Serialize, Deserialize)]
struct Progress {
    version: u32,
    size: usize,
    clues: Vec<Option<i64>>,
    max_area: usize,
    pool: Vec<Shape>,
    limits: Vec<usize>,
    attempts: Vec<u64>,
    complete: Vec<bool>,
    generators: Vec<Option<Generator>>,
    search: Option<SearchState>,
    stats: Stats,
    solution: Option<Vec<usize>>,
    elapsed: f64,
    generation_nodes: u64,
    runs: u64,
}
impl Progress {
    fn new(b: &Board, max_area: usize) -> Self {
        Self {
            version: 1,
            size: b.size,
            clues: b.clues.clone(),
            max_area,
            pool: vec![],
            limits: vec![0; b.n],
            attempts: vec![0; b.n],
            complete: vec![false; b.n],
            generators: (0..b.n).map(|_| None).collect(),
            search: None,
            stats: Stats::default(),
            solution: None,
            elapsed: 0.0,
            generation_nodes: 0,
            runs: 0,
        }
    }
    fn validate(&self, b: &Board, max_area: usize) -> Result<(), String> {
        if self.version != 1
            || self.size != b.size
            || self.clues != b.clues
            || self.max_area != max_area
        {
            return Err("Checkpoint does not match these clues, board size, area limit or engine version. Use a different checkpoint path or --fresh.".into());
        }
        let invalid = || Err("Invalid checkpoint data".into());
        if self.limits.len() != b.n
            || self.attempts.len() != b.n
            || self.complete.len() != b.n
            || self.generators.len() != b.n
            || self.limits.iter().any(|&v| v > max_area)
        {
            return invalid();
        }
        if self.pool.iter().any(|s| {
            s.mask == 0
                || s.mask & !b.full != 0
                || s.area != s.mask.count_ones() as i64
                || s.area > max_area as i64
                || s.cap
                    .is_some_and(|i| i >= b.n || s.mask & (1u128 << i) == 0)
        }) {
            return invalid();
        }
        let valid_path = |path: &Vec<usize>| {
            let mut m = 0;
            for &k in path {
                if k >= self.pool.len() || self.pool[k].mask & m != 0 {
                    return false;
                }
                m |= self.pool[k].mask;
            }
            true
        };
        if self
            .solution
            .as_ref()
            .is_some_and(|p| !valid_path(p) || !verify(b, &self.pool, p))
        {
            return invalid();
        }
        if self
            .search
            .as_ref()
            .is_some_and(|s| s.pending.iter().any(|p| !valid_path(p)))
        {
            return invalid();
        }
        for (i, g) in self.generators.iter().enumerate() {
            if let Some(g) = g {
                if g.root != i || g.limit == 0 || g.limit > max_area {
                    return invalid();
                }
                for w in &g.walkers {
                    if w.orbits.len() != b.n
                        || w.orbits
                            .iter()
                            .chain(&w.stack)
                            .chain(&w.seen)
                            .any(|m| m & !b.full != 0)
                    {
                        return invalid();
                    }
                }
            }
        }
        Ok(())
    }
}
struct Checkpoint {
    path: PathBuf,
    // OS lock is released even when the process is killed; the lock file stays.
    _lock: std::fs::File,
}
impl Checkpoint {
    fn open(path: &Path) -> Result<Self, String> {
        if let Some(parent) = path.parent().filter(|p| !p.as_os_str().is_empty()) {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let mut lock_name = path.as_os_str().to_os_string();
        lock_name.push(".lock");
        let lock_path = PathBuf::from(lock_name);
        let lock = std::fs::OpenOptions::new()
            .create(true)
            .truncate(false)
            .write(true)
            .open(lock_path)
            .map_err(|e| e.to_string())?;
        lock.try_lock()
            .map_err(|e| format!("Checkpoint is already in use or cannot be locked: {e}"))?;
        Ok(Self {
            path: path.to_owned(),
            _lock: lock,
        })
    }
    fn load(&self, b: &Board, max_area: usize, fresh: bool) -> Result<(Progress, bool), String> {
        if fresh || !self.path.exists() {
            return Ok((Progress::new(b, max_area), false));
        }
        let f = std::fs::File::open(&self.path).map_err(|e| e.to_string())?;
        let p: Progress = serde_json::from_reader(BufReader::new(f))
            .map_err(|e| format!("Cannot read checkpoint: {e}"))?;
        p.validate(b, max_area)?;
        Ok((p, true))
    }
    fn save(&self, p: &Progress) -> Result<(), String> {
        let temporary = self
            .path
            .with_extension(format!("tmp-{}", std::process::id()));
        let f = std::fs::File::create(&temporary).map_err(|e| e.to_string())?;
        let mut out = BufWriter::new(f);
        serde_json::to_writer(&mut out, p).map_err(|e| e.to_string())?;
        out.flush().map_err(|e| e.to_string())?;
        out.get_ref().sync_all().map_err(|e| e.to_string())?;
        std::fs::rename(&temporary, &self.path).map_err(|e| e.to_string())
    }
}
fn verify(b: &Board, pool: &[Shape], chosen: &[usize]) -> bool {
    let mut occupied = 0;
    let mut caps = 0;
    let mut areas = vec![0; b.n];
    for &k in chosen {
        let s = pool[k];
        if occupied & s.mask != 0 || !b.connected(s.mask) {
            return false;
        }
        let Some(actual) = b.shape(s.mask) else {
            return false;
        };
        if actual.cap != s.cap {
            return false;
        }
        occupied |= s.mask;
        for i in bits(s.mask) {
            areas[i] = s.area;
        }
        if let Some(c) = s.cap {
            caps |= 1u128 << c;
        }
    }
    if occupied != b.full || caps == 0 {
        return false;
    }
    let d = b.envelope(&areas, bits(caps).map(|i| (i, 0)));
    (0..b.n).all(|i| b.clues[i].is_none_or(|v| d[i] == v))
}
fn materialize(b: &Board, pool: &[Shape], chosen: &[usize]) -> Value {
    let mut cells = vec![Value::Null; b.n];
    for (id, &k) in chosen.iter().enumerate() {
        let s = pool[k];
        let color = format!("#{:06x}", ((id + 1) * 0x9e3779) & 0xffffff);
        for i in bits(s.mask) {
            cells[i] = json!({"starting_number":b.clues[i],"region_color":color,"is_capital":s.cap==Some(i),"capital_required":b.clues[i]==Some(0)});
        }
    }
    json!(cells.chunks(b.size).collect::<Vec<_>>())
}
#[cfg(test)]
fn solve(b: &Board, seconds: f64, max_area: usize, per_root: f64) -> Value {
    solve_resume(b, seconds, max_area, per_root, None, false).unwrap()
}
fn solve_resume(
    b: &Board,
    seconds: f64,
    max_area: usize,
    per_root: f64,
    checkpoint: Option<&Checkpoint>,
    fresh: bool,
) -> Result<Value, String> {
    let (mut p, resumed) = if let Some(store) = checkpoint {
        store.load(b, max_area, fresh)?
    } else {
        (Progress::new(b, max_area), false)
    };
    let started = Instant::now();
    let deadline = started + Duration::from_secs_f64(seconds);
    let mut last_save = Instant::now();
    let previous_elapsed = p.elapsed;
    let mut high = vec![max_area as i64; b.n];
    for i in bits(b.forced) {
        high[i] = 1;
    }
    let neg = b.envelope(
        &high,
        b.clues
            .iter()
            .enumerate()
            .filter_map(|(i, &v)| v.map(|v| (i, -v))),
    );
    let forbidden = (0..b.n)
        .filter(|&i| neg[i] < 0)
        .fold(0, |m, i| m | 1u128 << i);
    let mut seen: HashSet<_> = p.pool.iter().map(|s| s.mask).collect();
    p.runs += 1;
    let next = |i: usize, p: &Progress| {
        if let Some(g) = &p.generators[i] {
            g.limit
        } else if b.forced & (1u128 << i) != 0 {
            1
        } else {
            max_area.min(4.max(b.low[i] as usize).max(p.limits[i] * 2))
        }
    };
    let choices = |i: usize| {
        if b.forced & (1u128 << i) != 0 {
            1
        } else {
            (b.low[i] as usize..=max_area)
                .filter(|&a| {
                    !(b.clues[i] == Some(0) && a % 2 == 0)
                        && !(a == 1
                            && (b.clues[i].unwrap_or(0) > 0
                                || bits(b.adj[i]).any(|j| b.clues[j].unwrap_or(0) > 1)))
                })
                .count()
        }
    };
    // Save an initial checkpoint too, so an early interruption has a valid file.
    if let Some(store) = checkpoint {
        store.save(&p)?;
    }
    let mut cover: Vec<Vec<usize>> = vec![];
    while Instant::now() < deadline && p.solution.is_none() {
        if let Some(search) = p.search.as_mut() {
            if cover.is_empty() {
                cover = vec![vec![]; b.n];
                for (k, s) in p.pool.iter().enumerate() {
                    for i in bits(s.mask) {
                        cover[i].push(k);
                    }
                }
            }
            if let Some(solution) = search.step(b, &p.pool, &cover, max_area, &mut p.stats) {
                p.solution = Some(solution);
            } else if search.pending.is_empty() {
                p.search = None;
                if p.complete.iter().all(|&v| v) {
                    break;
                }
            }
        } else {
            let mut roots: Vec<_> = (0..b.n).filter(|&i| !p.complete[i]).collect();
            roots.sort_by_key(|&i| (next(i, &p), p.attempts[i], choices(i), i));
            if roots.is_empty() {
                break;
            }
            // A bounded chunk advances saved orbit stacks, never restarts a prefix.
            let root = roots[0];
            let limit = next(root, &p);
            if p.generators[root].is_none() {
                p.generators[root] = Some(Generator::new(b, root, limit));
            }
            p.attempts[root] += 1;
            let slice_deadline =
                deadline.min(Instant::now() + Duration::from_secs_f64(per_root.min(1.0)));
            let before = p.pool.len();
            let g = p.generators[root].as_mut().unwrap();
            for _ in 0..100000 {
                if Instant::now() >= slice_deadline || g.walkers.is_empty() {
                    break;
                }
                if let Some(s) = g.step(b, forbidden) {
                    if seen.insert(s.mask) {
                        p.pool.push(s);
                    }
                }
                p.generation_nodes += 1;
            }
            if g.walkers.is_empty() {
                p.limits[root] = limit;
                p.complete[root] = limit == max_area || b.forced & (1u128 << root) != 0;
                p.generators[root] = None;
            }
            if p.pool.len() != before || p.complete.iter().all(|&v| v) {
                // A larger pool invalidates old domain-dependent rejections.
                p.search = Some(SearchState::new());
                p.stats.rounds += 1;
                cover.clear();
            }
        }
        if last_save.elapsed() >= Duration::from_secs(5) {
            p.elapsed = previous_elapsed + started.elapsed().as_secs_f64();
            if let Some(store) = checkpoint {
                store.save(&p)?;
            }
            last_save = Instant::now();
        }
    }
    p.elapsed = previous_elapsed + started.elapsed().as_secs_f64();
    if let Some(store) = checkpoint {
        store.save(&p)?;
    }
    let solution = p
        .solution
        .as_ref()
        .map(|chosen| materialize(b, &p.pool, chosen));
    Ok(
        json!({"engine":"rust-u128","status":if solution.is_some(){"verified_solution"}else if Instant::now()>=deadline{"time_limit"}else{"sample_exhausted"},"elapsed_seconds":started.elapsed().as_secs_f64(),"total_elapsed_seconds":p.elapsed,"resumed":resumed,"checkpoint":checkpoint.map(|s|s.path.to_string_lossy().into_owned()),"checkpoint_runs":p.runs,"generation_nodes":p.generation_nodes,"pending_search_nodes":p.search.as_ref().map_or(0,|s|s.pending.len()),"max_area":max_area,"candidate_count":p.pool.len(),"roots_generated":p.attempts.iter().filter(|&&v|v>0).count(),"complete_candidate_roots":p.complete.iter().filter(|&&v|v).count(),"generation_calls":p.attempts.iter().sum::<u64>(),"largest_generation_limit":(0..b.n).map(|i|p.generators[i].as_ref().map_or(p.limits[i],|g|g.limit)).max(),"board_cells":b.n,"best_partial_coverage":p.stats.best,"initial_forbidden_capitols":bits(forbidden).map(|i|vec![i/b.size+1,i%b.size+1]).collect::<Vec<_>>(),"statistics":{"nodes":p.stats.nodes,"travel_prunes":p.stats.travel_prunes,"cover_prunes":p.stats.cover_prunes,"candidate_support_prunes":p.stats.support_prunes,"equivalent_partition_prunes":p.stats.equivalent_prunes,"search_rounds":p.stats.rounds},"scope":"Clues only. Bounded candidate enumeration; an unsuccessful run does not prove global impossibility.","solution":solution}),
    )
}
fn read_board(value: &Value) -> Result<Board, String> {
    let grid = value
        .get("saved")
        .or_else(|| value.get("grid"))
        .unwrap_or(value);
    let rows = grid.as_array().ok_or("Expected grid or project JSON")?;
    let size = rows.len();
    let mut clues = vec![];
    for row in rows {
        let row = row.as_array().ok_or("Expected rows")?;
        if row.len() != size {
            return Err("Expected square grid".into());
        }
        for cell in row {
            let v = cell.get("starting_number").unwrap_or(cell);
            clues.push(if v.is_null() {
                None
            } else {
                Some(
                    v.as_i64()
                        .or_else(|| {
                            v.as_f64()
                                .filter(|x| {
                                    x.is_finite()
                                        && x.fract() == 0.0
                                        && *x >= 0.0
                                        && *x <= 1_000_000_000.0
                                })
                                .map(|x| x as i64)
                        })
                        .ok_or("Clues must be nonnegative integers or null")?,
                )
            });
        }
    }
    Board::new(clues, size)
}
fn absolute_path(path: &Path) -> Result<PathBuf, String> {
    if path.exists() {
        return path.canonicalize().map_err(|e| e.to_string());
    }
    let absolute = std::path::absolute(path).map_err(|e| e.to_string())?;
    let mut normalized = PathBuf::new();
    for component in absolute.components() {
        match component {
            std::path::Component::ParentDir => {
                normalized.pop();
            }
            std::path::Component::CurDir => {}
            other => normalized.push(other.as_os_str()),
        }
        // Resolve existing parent symlinks even when the final file is new.
        if normalized.exists() {
            normalized = normalized.canonicalize().map_err(|e| e.to_string())?;
        }
    }
    Ok(normalized)
}
fn run() -> Result<(), String> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let mut seconds = 120.0;
    let mut per_root = 0.3;
    let mut max_area = None;
    let mut input = None;
    let mut output = None;
    let mut checkpoint_path = None;
    let mut fresh = false;
    let mut i = 0;
    while i < args.len() {
        let flag = &args[i];
        if flag == "--fresh" {
            fresh = true;
            i += 1;
            continue;
        }
        if flag == "--help" {
            println!("decomposition --input GRID.json [--seconds 120] [--max-area 98] [--per-root-seconds .3] [--output REPORT.json] [--checkpoint CHECKPOINT.json] [--fresh]\nInput: clue matrix, editor grid or project JSON. Use --input - for stdin. Output defaults to stdout.");
            return Ok(());
        }
        i += 1;
        let v = args.get(i).ok_or("Missing option value")?;
        match flag.as_str() {
            "--input" => input = Some(v.clone()),
            "--output" => output = Some(v.clone()),
            "--checkpoint" => checkpoint_path = Some(PathBuf::from(v)),
            "--seconds" => seconds = v.parse::<f64>().map_err(|e| e.to_string())?,
            "--per-root-seconds" => per_root = v.parse::<f64>().map_err(|e| e.to_string())?,
            "--max-area" => max_area = Some(v.parse::<usize>().map_err(|e| e.to_string())?),
            _ => return Err(format!("Unknown option {flag}")),
        }
        i += 1;
    }
    if !seconds.is_finite()
        || !(0.0..=86400.0).contains(&seconds)
        || !per_root.is_finite()
        || per_root <= 0.0
        || per_root > 86400.0
    {
        return Err("Seconds must be 0..86400; per-root seconds must be >0 and <=86400".into());
    }
    let input = input.ok_or("Supply --input GRID.json (or --input -)")?;
    let source = if input == "-" {
        std::io::read_to_string(std::io::stdin()).map_err(|e| e.to_string())?
    } else {
        std::fs::read_to_string(input).map_err(|e| e.to_string())?
    };
    let value: Value = serde_json::from_str(&source).map_err(|e| e.to_string())?;
    let board = read_board(&value)?;
    let max_area = max_area.unwrap_or(98.min(board.n));
    if max_area == 0 || max_area > board.n {
        return Err(format!("Maximum area must be 1..{}", board.n));
    }
    if fresh && checkpoint_path.is_none() {
        return Err("--fresh requires --checkpoint".into());
    }
    if let (Some(checkpoint), Some(output)) = (&checkpoint_path, &output) {
        if absolute_path(checkpoint)? == absolute_path(Path::new(output))? {
            return Err("Checkpoint and output must be different files".into());
        }
    }
    let checkpoint = checkpoint_path
        .as_deref()
        .map(Checkpoint::open)
        .transpose()?;
    let report = solve_resume(
        &board,
        seconds,
        max_area,
        per_root,
        checkpoint.as_ref(),
        fresh,
    )?;
    let rendered = serde_json::to_string_pretty(&report).unwrap() + "\n";
    if let Some(path) = output {
        std::fs::write(path, rendered).map_err(|e| e.to_string())?
    } else {
        print!("{rendered}")
    }
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("{e}");
        std::process::exit(2)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    // Frozen reference results from model.py and symmetric_shapes.py for all
    // 511 nonempty subsets of a 3x3 board, including disconnected shapes.
    #[test]
    fn python_geometry_oracle() {
        let b = Board::new(vec![None; 9], 3).unwrap();
        let rows: Value =
            serde_json::from_str(include_str!("../tests/geometry-oracle.json")).unwrap();
        for row in rows.as_array().unwrap() {
            let m = row[0].as_u64().unwrap() as u128;
            assert_eq!(
                b.connected(m),
                row[1].as_bool().unwrap(),
                "connectivity {m}"
            );
            let shape = b.shape(m);
            assert_eq!(shape.is_some(), row[2].as_bool().unwrap(), "symmetry {m}");
            if let Some(shape) = shape {
                assert_eq!(
                    shape.cap,
                    row[3].as_u64().map(|x| x as usize),
                    "capitol {m}"
                );
            }
        }
    }
    #[test]
    fn orbit_generation_matches_brute_force() {
        let b = Board::new(vec![None; 9], 3).unwrap();
        for root in 0..9 {
            let (shapes, done) = generate(
                &b,
                root,
                9,
                Instant::now() + Duration::from_secs(5),
                100000,
                0,
            );
            assert!(done);
            let actual: HashSet<_> = shapes.iter().map(|s| s.mask).collect();
            let expected: HashSet<_> = (1u128..512)
                .filter(|&m| m & (1 << root) != 0 && b.assess(m, 0).is_some())
                .collect();
            assert_eq!(actual, expected, "root {root}");
        }
    }
    #[test]
    fn generator_resume_preserves_exact_sequence_and_high_bits() {
        let b = Board::new(vec![None; 121], 11).unwrap();
        let mut g = Generator::new(&b, 120, 4);
        for _ in 0..37 {
            g.step(&b, 0);
        }
        let data = serde_json::to_vec(&g).unwrap();
        let mut restored: Generator = serde_json::from_slice(&data).unwrap();
        for _ in 0..5000 {
            assert_eq!(
                g.step(&b, 0).map(|s| (s.mask, s.cap)),
                restored.step(&b, 0).map(|s| (s.mask, s.cap))
            );
            assert_eq!(g.visited, restored.visited);
            if g.walkers.is_empty() {
                assert!(restored.walkers.is_empty());
                break;
            }
        }
    }
    #[test]
    fn search_frontier_roundtrip_keeps_remaining_work() {
        let b = Board::new(vec![None; 4], 2).unwrap();
        let pool: Vec<_> = (0..4).map(|i| b.shape(1 << i).unwrap()).collect();
        let cover: Vec<_> = (0..4).map(|i| vec![i]).collect();
        let mut original = SearchState::new();
        let mut stats = Stats::default();
        assert!(original.step(&b, &pool, &cover, 4, &mut stats).is_none());
        assert!(original.step(&b, &pool, &cover, 4, &mut stats).is_none());
        let mut restored: SearchState =
            serde_json::from_slice(&serde_json::to_vec(&original).unwrap()).unwrap();
        let mut other_stats = Stats::default();
        loop {
            let a = original.step(&b, &pool, &cover, 4, &mut stats);
            let z = restored.step(&b, &pool, &cover, 4, &mut other_stats);
            assert_eq!(a, z);
            assert_eq!(original.pending, restored.pending);
            if a.is_some() {
                break;
            }
        }
        assert_eq!(other_stats.nodes, 3);
    }
    #[test]
    fn highest_cell_and_connectivity() {
        let b = Board::new(vec![None; 121], 11).unwrap();
        assert!(b.connected(1u128 << 120));
        assert!(!b.connected(1 | (1u128 << 120)));
        assert_eq!(bits(b.full).count(), 121);
    }
    #[test]
    fn universal_fixed_cell() {
        let b = Board::new(vec![None; 9], 3).unwrap();
        assert_eq!(b.shape(0b111).unwrap().cap, None);
        assert_eq!(b.shape(0b111111111).unwrap().cap, None);
        assert_eq!(b.shape(1).unwrap().cap, Some(0));
        assert_eq!(
            b.shape((1 << 1) | (1 << 3) | (1 << 4) | (1 << 5) | (1 << 7))
                .unwrap()
                .cap,
            None
        );
    }
    #[test]
    fn exhaustive_dominoes() {
        let b = Board::new(vec![None; 4], 2).unwrap();
        let (shapes, done) = generate(&b, 0, 2, Instant::now() + Duration::from_secs(2), 100000, 0);
        assert!(done);
        assert_eq!(shapes.len(), 3);
    }
    #[test]
    fn zero_budget_is_not_impossibility() {
        let b = Board::new(vec![None; 4], 2).unwrap();
        let r = solve(&b, 0.0, 4, 0.01);
        assert_eq!(r["status"], "time_limit");
        assert!(r["solution"].is_null());
    }
    #[test]
    fn exact_distances() {
        let b = Board::new(vec![None; 4], 2).unwrap();
        assert_eq!(
            b.envelope(&[1, 3, 4, 2], [(0, 0)].into_iter()),
            vec![0, 1, 1, 3]
        );
    }
}
