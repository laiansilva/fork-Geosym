from devito.types.tensor import TensorFunction, TensorTimeFunction, VectorFunction, VectorTimeFunction, tens_func
import numpy as np

from sympy import symbols, Matrix, ones


def matrix_init(model):
    def cij(i, j):
        ii, jj = min(i, j), max(i, j)
        if (ii == jj or (ii <= model.dim and jj <= model.dim)):
            return symbols('C%s%s' % (ii, jj))
        return 0

    d = model.dim*2 + model.dim-2
    Cij = [[cij(i, j) for i in range(1, d)] for j in range(1, d)]
    return Matrix(Cij)


def generate_Clam(model):
    def c_lam(i, j):
        ii, jj = min(i, j), max(i, j)
        if (ii <= model.dim and jj <= model.dim):
            return 1
        return 0

    d = model.dim*2 + model.dim-2
    Clam = [[c_lam(i, j) for i in range(1, d)] for j in range(1, d)]
    return Matrix(Clam)


def generate_Cmu(model):
    def c_mu(i, j):
        ii, jj = min(i, j), max(i, j)
        if (ii == jj):
           if  ii <= model.dim:
               return 2
           else: 
               return 1
        return 0

    d = model.dim*2 + model.dim-2
    Cmu = [[c_mu(i, j) for i in range(1, d)] for j in range(1, d)]
    return Matrix(Cmu)


def D(self, shift=None):
    """
    Returns the result of matrix D applied over the TensorFunction.
    """
    if not self.is_TensorValued:
        raise TypeError("The object must be a Tensor object")

    M = tensor(self) if self.shape[0] != self.shape[1] else self

    comps = []
    func = tens_func(self)
    for j, d in enumerate(self.space_dimensions):
        comps.append(sum([getattr(M[j, i], 'd%s' % d.name)
                         for i, d in enumerate(self.space_dimensions)]))
    return func._new(comps)


def S(self, shift=None):
    """
    Returns the result of transposed matrix D applied over the VectorFunction.
    """
    if not self.is_VectorValued:
        raise TypeError("The object must be a Vector object")

    derivs = ['d%s' % d.name for d in self.space_dimensions]

    comp = []
    comp.append(getattr(self[0], derivs[0]))
    comp.append(getattr(self[1], derivs[1]))
    if len(self.space_dimensions) == 3:
        comp.append(getattr(self[2], derivs[2]))
        comp.append(getattr(self[1], derivs[2]) + getattr(self[2], derivs[1]))
        comp.append(getattr(self[0], derivs[2]) + getattr(self[2], derivs[0]))
    comp.append(getattr(self[0], derivs[1]) + getattr(self[1], derivs[0]))

    func = tens_func(self)

    return func._new(comp)


def vec(self):
    if not self.is_TensorValued:
        raise TypeError("The object must be a Tensor object")
    if self.shape[0] != self.shape[1]:
        raise Exception("This object is already represented by its vector form.")

    order = ([(0, 0), (1, 1), (2, 2), (1, 2), (0, 2), (0, 1)]
             if len(self.space_dimensions) == 3 else [(0, 0), (1, 1), (0, 1)])
    comp = [self[o[0], o[1]] for o in order]
    func = tens_func(self)
    return func(comp)


def tensor(self):
    if not self.is_TensorValued:
        raise TypeError("The object must be a Tensor object")
    if self.shape[0] == self.shape[1]:
        raise Exception("This object is already represented by its tensor form.")

    ndim = len(self.space_dimensions)
    M = np.zeros((ndim, ndim), dtype=np.dtype(object))
    M[0, 0] = self[0]
    M[1, 1] = self[1]
    if len(self.space_dimensions) == 3:
        M[2, 2] = self[2]
        M[2, 1] = self[3]
        M[1, 2] = self[3]
        M[2, 0] = self[4]
        M[0, 2] = self[4]
    M[1, 0] = self[-1]
    M[0, 1] = self[-1]

    func = tens_func(self)
    return func._new(M)


def gather(a1, a2):
    # vector e tensor obrigatoriamente, e tambem nessa ordem. Se tiver valor zero, quero adicionar ndim zeros

    expected_a1_types = [int, VectorFunction, VectorTimeFunction]
    expected_a2_types = [TensorFunction, TensorTimeFunction]

    if type(a1) not in expected_a1_types:
        raise ValueError("a1 must be a VectorFunction or a Integer")
    if type(a2) not in expected_a2_types:
        raise ValueError("a2 must be a TensorFunction")

    if(a2.shape[0] > 1 and a2.shape[1] > 1):
        raise Exception("Tensor Function must be at its vector representation")


    if type(a1) is int:
        a1 = Matrix([ones(len(a2.space_dimensions), 1)*a1])    
    else:
        a1 = Matrix(a1)

    a2 = Matrix(a2)
    
    if a1.cols > 1:
        a1 = a1.T
    if a2.cols > 1:
        a2 = a2.T

    return Matrix.vstack(a1, a2)
