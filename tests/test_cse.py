import pytest

from sympy import Ge, Lt
from sympy.core.mul import _mulsort

from conftest import assert_structure
from devito import (Grid, Function, TimeFunction, ConditionalDimension, Eq,  # noqa
                    Operator, cos)
from devito.finite_differences.differentiable import diffify
from devito.ir import DummyEq, FindNodes, FindSymbols, Conditional
from devito.ir.support import generator
from devito.passes.clusters.cse import CTemp, _cse
from devito.symbolics import indexify
from devito.types import Array, Symbol, Temp


@pytest.mark.parametrize('exprs,expected,min_cost', [
    # Simple cases
    (['Eq(tu, 2/(t0 + t1))', 'Eq(ti0, t0 + t1)', 'Eq(ti1, t0 + t1)'],
     ['t0 + t1', '2/r0', 'r0', 'r0'], 0),
    (['Eq(tu, 2/(t0 + t1))', 'Eq(ti0, 2/(t0 + t1) + 1)', 'Eq(ti1, 2/(t0 + t1) + 1)'],
     ['2/(t0 + t1)', 'r1', 'r1 + 1', 'r0', 'r0'], 0),
    (['Eq(tu, (tv + tw + 5.)*(ti0 + ti1) + (t0 + t1)*(ti0 + ti1))'],
     ['ti0[x, y, z] + ti1[x, y, z]',
      'r0*(t0 + t1) + r0*(tv[t, x, y, z] + tw[t, x, y, z] + 5.0)'], 0),
    (['Eq(tu, t0/t1)', 'Eq(ti0, 2 + t0/t1)', 'Eq(ti1, 2 + t0/t1)'],
     ['t0/t1', 'r1', 'r1 + 2', 'r0', 'r0'], 0),
    # Across expressions
    (['Eq(tu, tv*4 + tw*5 + tw*5*t0)', 'Eq(tv, tw*5)'],
     ['5*tw[t, x, y, z]', 'r0 + 5*t0*tw[t, x, y, z] + 4*tv[t, x, y, z]', 'r0'], 0),
    # Intersecting
    pytest.param(['Eq(tu, ti0*ti1 + ti0*ti1*t0 + ti0*ti1*t0*t1)'],
                 ['ti0*ti1', 'r0', 'r0*t0', 'r0*t0*t1'], 0,
                 marks=pytest.mark.xfail),
    # Divisions (== powers with negative exponenet) are always captured
    (['Eq(tu, tv**-1*(tw*5 + tw*5*t0))', 'Eq(ti0, tv**-1*t0)'],
     ['1/tv[t, x, y, z]', 'r0*(5*t0*tw[t, x, y, z] + 5*tw[t, x, y, z])', 'r0*t0'], 0),
    # `compact_temporaries` must detect chains of isolated temporaries
    (['Eq(t0, tv)', 'Eq(t1, t0)', 'Eq(t2, t1)', 'Eq(tu, t2)'],
     ['tv[t, x, y, z]'], 0),
    # Dimension-independent flow+anti dependences should be a stopper for CSE
    (['Eq(t0, cos(t1))', 'Eq(t1, 5)', 'Eq(t2, cos(t1))'],
     ['cos(t1)', '5', 'cos(t1)'], 0),
    (['Eq(tu, tv + 1)', 'Eq(tv, tu)', 'Eq(tw, tv + 1)'],
     ['tv[t, x, y, z] + 1', 'tu[t, x, y, z]', 'tv[t, x, y, z] + 1'], 0),
    # Dimension-independent flow (but not anti) dependences are OK instead as
    # long as the temporaries are introduced after the write
    (['Eq(tu.forward, tu.dx + 1)', 'Eq(tv.forward, tv.dx + 1)',
      'Eq(tw.forward, tv.dt + 1)', 'Eq(tz.forward, tv.dt + 2)'],
     ['1/h_x', '-r1*tu[t, x, y, z] + r1*tu[t, x + 1, y, z] + 1',
      '-r1*tv[t, x, y, z] + r1*tv[t, x + 1, y, z] + 1',
      '1/dt', '-r2*tv[t, x, y, z] + r2*tv[t + 1, x, y, z]',
      'r0 + 1', 'r0 + 2'], 0),
    # Fancy use case with lots of temporaries
    (['Eq(tu.forward, tu.dx + 1)', 'Eq(tv.forward, tv.dx + 1)',
      'Eq(tw.forward, tv.dt.dx2.dy2 + 1)', 'Eq(tz.forward, tv.dt.dy2.dx2 + 2)'],
     ['1/h_x', '-r11*tu[t, x, y, z] + r11*tu[t, x + 1, y, z] + 1',
      '-r11*tv[t, x, y, z] + r11*tv[t, x + 1, y, z] + 1',
      '1/dt', '-r12*tv[t, x - 1, y - 1, z] + r12*tv[t + 1, x - 1, y - 1, z]',
      '-r12*tv[t, x + 1, y - 1, z] + r12*tv[t + 1, x + 1, y - 1, z]',
      '-r12*tv[t, x, y - 1, z] + r12*tv[t + 1, x, y - 1, z]',
      '-r12*tv[t, x - 1, y + 1, z] + r12*tv[t + 1, x - 1, y + 1, z]',
      '-r12*tv[t, x + 1, y + 1, z] + r12*tv[t + 1, x + 1, y + 1, z]',
      '-r12*tv[t, x, y + 1, z] + r12*tv[t + 1, x, y + 1, z]',
      '-r12*tv[t, x - 1, y, z] + r12*tv[t + 1, x - 1, y, z]',
      '-r12*tv[t, x + 1, y, z] + r12*tv[t + 1, x + 1, y, z]',
      '-r12*tv[t, x, y, z] + r12*tv[t + 1, x, y, z]',
      'h_x**(-2)', '-2.0*r13', 'h_y**(-2)', '-2.0*r14',
      'r10*(r13*r6 + r13*r7 + r8*r9) + r14*(r0*r13 + r1*r13 + r2*r9) + ' +
      'r14*(r13*r3 + r13*r4 + r5*r9) + 1',
      'r13*(r0*r14 + r10*r6 + r14*r3) + r13*(r1*r14 + r10*r7 + r14*r4) + ' +
      'r9*(r10*r8 + r14*r2 + r14*r5) + 2'], 0),
    # Existing temporaries from nested Function as index
    (['Eq(e0, fx[x])', 'Eq(tu, cos(-tu[t, e0, y, z]) + tv[t, x, y, z])',
      'Eq(tv, cos(tu[t, e0, y, z]) + tw)'],
     ['fx[x]', 'cos(tu[t, e0, y, z])', 'r0 + tv[t, x, y, z]', 'r0 + tw[t, x, y, z]'], 0),
    # Make sure -x isn't factorized with default minimum cse cost
    (['Eq(e0, fx[x])', 'Eq(tu, -tu[t, e0, y, z] + tv[t, x, y, z])',
      'Eq(tv, -tu[t, e0, y, z] + tw)'],
     ['fx[x]', '-tu[t, e0, y, z] + tv[t, x, y, z]',
      '-tu[t, e0, y, z] + tw[t, x, y, z]'], 1)
])
def test_default_algo(exprs, expected, min_cost):
    """Test common subexpressions elimination."""
    grid = Grid((3, 3, 3))
    x, y, z = grid.dimensions
    t = grid.stepping_dim  # noqa

    tu = TimeFunction(name="tu", grid=grid, space_order=2)  # noqa
    tv = TimeFunction(name="tv", grid=grid, space_order=2)  # noqa
    tw = TimeFunction(name="tw", grid=grid, space_order=2)  # noqa
    tz = TimeFunction(name="tz", grid=grid, space_order=2)  # noqa
    fx = Function(name="fx", grid=grid, dimensions=(x,), shape=(3,))  # noqa
    ti0 = Array(name='ti0', shape=(3, 5, 7), dimensions=(x, y, z)).indexify()  # noqa
    ti1 = Array(name='ti1', shape=(3, 5, 7), dimensions=(x, y, z)).indexify()  # noqa
    t0 = CTemp(name='t0')  # noqa
    t1 = CTemp(name='t1')  # noqa
    t2 = CTemp(name='t2')  # noqa
    # Needs to not be a Temp to mimic nested index extraction and prevent
    # cse to compact the temporary back.
    e0 = Symbol(name='e0')  # noqa

    # List comprehension would need explicit locals/globals mappings to eval
    for i, e in enumerate(list(exprs)):
        exprs[i] = DummyEq(indexify(diffify(eval(e).evaluate)))

    counter = generator()
    make = lambda: CTemp(name='r%d' % counter()).indexify()
    processed = _cse(exprs, make, min_cost)

    assert len(processed) == len(expected)
    assert all(str(i.rhs) == j for i, j in zip(processed, expected))


def test_temp_order():
    # Test order of classes inserted to Sympy's core ordering
    a = Temp(name='r6')
    b = CTemp(name='r6')
    c = Symbol(name='r6')

    args = [b, a, c]

    _mulsort(args)

    assert type(args[0]) is Symbol
    assert type(args[1]) is Temp
    assert type(args[2]) is CTemp


def test_w_conditionals():
    grid = Grid(shape=(10, 10, 10))
    x, _, _ = grid.dimensions

    cd = ConditionalDimension(name='cd', parent=x, condition=Ge(x, 4),
                              indirect=True)

    f = Function(name='f', grid=grid)
    g = Function(name='g', grid=grid)
    h = Function(name='h', grid=grid)
    a0 = Function(name='a0', grid=grid)
    a1 = Function(name='a1', grid=grid)

    eqns = [Eq(h, a0, implicit_dims=cd),
            Eq(a0, a0 + f*g, implicit_dims=cd),
            Eq(a1, a1 + f*g, implicit_dims=cd)]

    op = Operator(eqns)

    assert_structure(op, ['x,y,z'], 'xyz')
    assert len(FindNodes(Conditional).visit(op)) == 1


def test_w_multi_conditionals():
    grid = Grid(shape=(10, 10, 10))
    x, _, _ = grid.dimensions

    cd = ConditionalDimension(name='cd', parent=x, condition=Ge(x, 4),
                              indirect=True)

    cd2 = ConditionalDimension(name='cd2', parent=x, condition=Lt(x, 4),
                               indirect=True)

    f = Function(name='f', grid=grid)
    g = Function(name='g', grid=grid)
    h = Function(name='h', grid=grid)
    a0 = Function(name='a0', grid=grid)
    a1 = Function(name='a1', grid=grid)
    a2 = Function(name='a2', grid=grid)
    a3 = Function(name='a3', grid=grid)

    eq0 = Eq(h, a0, implicit_dims=cd)
    eq1 = Eq(a0, a0 + f*g, implicit_dims=cd)
    eq2 = Eq(a1, a1 + f*g, implicit_dims=cd)
    eq3 = Eq(a2, a2 + f*g, implicit_dims=cd2)
    eq4 = Eq(a3, a3 + f*g, implicit_dims=cd2)

    op = Operator([eq0, eq1, eq3])

    assert_structure(op, ['x,y,z'], 'xyz')
    assert len(FindNodes(Conditional).visit(op)) == 2

    tmps = [s for s in FindSymbols().visit(op) if s.name.startswith('r')]
    assert len(tmps) == 0

    op = Operator([eq0, eq1, eq3, eq4])

    assert_structure(op, ['x,y,z'], 'xyz')
    assert len(FindNodes(Conditional).visit(op)) == 2

    tmps = [s for s in FindSymbols().visit(op) if s.name.startswith('r')]
    assert len(tmps) == 1

    op = Operator([eq0, eq1, eq2, eq3, eq4])

    assert_structure(op, ['x,y,z'], 'xyz')
    assert len(FindNodes(Conditional).visit(op)) == 2

    tmps = [s for s in FindSymbols().visit(op) if s.name.startswith('r')]
    assert len(tmps) == 2
