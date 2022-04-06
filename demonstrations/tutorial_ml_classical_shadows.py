r"""
Machine learning for quantum many-body problems
==============================================================

.. meta::
    :property="og:description": Machine learning for many-body problems
    :property="og:image": https://pennylane.ai/qml/_images/ml_classical_shadow.png

.. related::
    tutorial_classical_shadows Classical Shadows


*Author: PennyLane dev team. Posted: XX. Last Updated: XX April 2022*


Storing and processing a complete description of an :math:`n`-qubit quantum mechanical
system is challenging because the density matrices involved become classically intractable
due to the number of classical bits scaling exponentially in :math:`n` as :math:`O(2^{n})`.
Therefore, there lies a need for having a more efficient classical representation of the
quantum state. The quantum community recently addressed this challenge by using the classical
shadow formalism, which allows one to build a concise classical description of the state of
a quantum system using randomized single-qubit measurements. It was argued in Ref. [#preskill]_
that combining classical shadows with classical machine learning enables using methods to
efficiently predict properties of the quantum systems such as the expectation value of a
Hamiltonian, correlations functions and entanglement entropies.

.. figure:: /demonstrations/ml_classical_shadows/class_shadow_ml.png
   :align: center
   :width: 100 %
   :alt: Combining ML with Classical Shadow

   Combining machine learning and classical shadow


In this demo, we demonstrate one of the ideas presented in Ref. [#preskill]_ for using classical
shadow formalism with classical machine learning to predict the ground-state properties of the
2D antiferromagnetic Heisenberg model. We begin by first learning how to build the Heisenberg model,
compute its ground state properties and compute its classical shadow. Finally, we demonstrate
using kernel-based learning models for learning these classical shadows and predicting the ground
state properties from them. So let's get started!

Building the 2D Heisenberg Model
---------------------------------

We define a two-dimensional antiferromagnetic Heisenberg model as a square
lattice, where each site is occupied by a spin-1/2 particle. The antiferromagnetic
nature and the overall physics of this model depends strongly on the couplings
:math:`J_{ij}` present between the spins :math:`\sigma^{z}_{i}` and
:math:`\sigma^{z}_{j}`, and help determine the overall Hamiltonian associated
with the model as following:

.. math::  H = \sum_{i < j} J_{ij}(X_i X_j + Y_i Y_j + Z_i Z_j) .

Here, we consider the family of Hamiltonians where all the couplings :math:`J_{ij}`
are sampled uniformly from [0, 2]. For defining each model, we build a coupling matrix
:math:`J` by providing the number of rows :math:`N_r` and columns :math:`N_c` present
in the square lattice. The shape of this matrix will be :math:`N_s \times N_s`,
where :math:`N_s = N_r \times N_c` is the total number of spin particles present in the model.


"""

import pennylane.numpy as np
import numpy as anp
import itertools as it


def build_coupling_mats(num_mats, num_rows, num_cols):
    """Build the coupling matrices for the 2D spin lattice of Heisenberg Model"""
    num_spins = num_rows * num_cols
    coupling_mats = np.zeros((num_mats, num_spins, num_spins))
    coup_term_mat = anp.random.RandomState(24).uniform(
        0, 2, size=(num_mats, 2 * num_rows * num_cols - num_rows - num_cols)
    )
    for itr in range(num_mats):
        # store coupling terms for each matrix as an iterator
        coup_terms = iter(coup_term_mat[itr])
        for i, j in it.product(range(num_spins), range(num_spins)):
            if not coupling_mats[itr][i][j]:
                if (j % num_cols and j - i == 1) or (j - i == num_cols):
                    coupling_mats[itr][i][j] = next(coup_terms)
                    coupling_mats[itr][j][i] = coupling_mats[itr][i][j]
    return coupling_mats


######################################################################
# For this demo, we study the model with four spins arranged on the nodes of
# a square lattice that would require four qubits for the simulation, i.e.,
# one qubit for one spin each. For constructing an instance of this model,
# we first build the coupling matrix using our previously defined function.
#

Nr, Nc = 2, 2
num_qubits = Nr * Nc  # Ns
J_mat = build_coupling_mats(1, Nr, Nc)[0]


######################################################################
# We can visualize the model instance by representing the coupling matrix as a
# ``networkx`` graph:

import matplotlib.pyplot as plt
import networkx as nx

G = nx.from_numpy_matrix(np.matrix(J_mat), create_using=nx.DiGraph)
pos = {i: (i % Nc, -(i // Nc)) for i in G.nodes()}
edge_labels = {(x, y): np.round(J_mat[x, y], 2) for x, y in G.edges()}
weights = [x + 1.5 for x in list(nx.get_edge_attributes(G, "weight").values())]

nx.draw(
    G,
    pos,
    node_color="lightblue",
    with_labels=True,
    node_size=600,
    width=weights,
    edge_color="firebrick",
)
nx.draw_networkx_edge_labels(G, pos=pos, edge_labels=edge_labels)
plt.show()


######################################################################
# We then use the same coupling matrix :math:`J_mat` to obtain the Hamiltonian
# :math:`H` for the model we have instantiated above. 
#

import pennylane as qml

def Hamiltonian(J_mat):
    coeffs, ops = [], []
    for i in range(J_mat.shape[0]):
        for j in range(i + 1, J_mat.shape[0]):
            for op in [qml.PauliX, qml.PauliY, qml.PauliZ]:
                coeff = J_mat[i, j]
                if coeff:
                    coeffs.append(coeff)
                    ops.append(op(i) @ op(j))
    H = qml.Hamiltonian(coeffs, ops)
    return H

print(Hamiltonian(J_mat))


######################################################################
# For the Heisenberg model, a propetry of interest is usally the two-body
# correlation function :math:`C_{ij}`, which for a pair of spins :math:`\sigma^{z}_{i}`
# and :math:`\sigma^{z}_{j}` is defined as:
#
# .. math::  \hat{C}_{ij} = \frac{1}{3} (X_i X_j + Y_iY_j + Z_iZ_j)
#
# Expectation value of each such element :math:`\hat{C}_{ij}` with respect to
# the ground state :math:`|\psi_{0}\rangle` of the model can be used to build
# the correlation matrix :math:`C`, such that:
#
# .. math:: {C}_{ij} = \langle \hat{C}_{ij} \rangle = \frac{1}{3} \langle \psi_{0} | X_i X_j + Y_iY_j + Z_iZ_j | \psi_{0} \rangle
#


def corr_function_op(i, j):
    """Build the correlation function operator :math:`\hat{C}_{ij}` for Heisenberg Model"""
    ops = []
    for op in [qml.PauliX, qml.PauliY, qml.PauliZ]:
        ops.append(op(i) @ op(j)) if i != j else ops.append(qml.Identity(i))
    return ops


######################################################################
# To calculate the exact ground state :math:`|\psi_{0}\rangle` of the
# model, we first diagonalize its corresponding Hamiltonian :math:`H`
# and obtain the eigenvector corresponding to the smallest eigenvalue. 
#

import scipy as sp

ham = Hamiltonian(J_mat)
eigvals, eigvecs = sp.sparse.linalg.eigs(qml.utils.sparse_hamiltonian(ham))
psi0 = eigvecs[:, np.argmin(eigvals)]


######################################################################
# We then build a circuit that initializes the qubits into the quantum
# state represented by this eigenvector and measures the expectation value of
# the provided set of observables.
#

dev_exact = qml.device("default.qubit", wires=num_qubits) # for exact simulation

def circuit(psi, observables):
    psi = psi / np.linalg.norm(psi) # normalize the state
    qml.QubitStateVector(psi, wires=range(num_qubits))
    return [qml.expval(o) for o in observables]

circuit_exact = qml.QNode(circuit, dev_exact)


######################################################################
# Finally, we execute this circuit to obtain the exact correlation matrix
# :math:`C`. We compute the correlation operators :math:`\hat{C}_{ij}` and
# their expectation values with respect to the ground state :math:`|\psi_0\rangle`.
#

coups = list(it.product(range(num_qubits), repeat=2))
corrs = [corr_function_op(i, j) for i, j in coups]
expval_exact = np.zeros((num_qubits, num_qubits))

for i, j in coups:
    corrs = corr_function_op(i, j)
    if i == j:
        expval_exact[i][j] = 1.0
    else:
        expval_exact[i][j] = (
            np.sum(np.array([circuit_exact(psi0, observables=[o]) for o in corrs]).T) / 3
        )
        expval_exact[j][i] = expval_exact[i][j]

#########################################################################
# Once built, we can visualize :math:`C` as an image uing the matplotlib
# function `imshow()``.
#

fig, ax = plt.subplots(1, 1, figsize=(6, 6))
im = ax.imshow(expval_exact, cmap=plt.get_cmap("RdBu"), vmin=-1, vmax=1)
ax.xaxis.set_ticks(range(num_qubits))
ax.yaxis.set_ticks(range(num_qubits))
ax.xaxis.set_tick_params(labelsize=18)
ax.yaxis.set_tick_params(labelsize=18)
ax.set_title("Exact Correlation Matrix", fontsize=18)

bar = fig.colorbar(im, pad=0.05, shrink=0.82)
bar.set_label(r"$C_{ij}$", fontsize=18, rotation=0)
bar.ax.tick_params(labelsize=14)
plt.show()


######################################################################
# Constructing Classical Shadows
# ------------------------------
#


######################################################################
# Now that we have built our Heisenberg model, the next step is to construct
# a classical shadow representation for it. To build an approximate
# classical representation of an :math:`n`-qubit quantum state :math:`\rho`,
# we perform randomized single-qubit measurements on :math:`T`-copies of
# :math:`\rho`. Each measurement is chosen randomly among the Pauli bases
# :math:`X`, :math:`Y`, or :math:`Z` to yield random :math:`n` pure product
# states :math:`|s_i\rangle` for each copy:
#
# .. math::  S_T(\rho) = \big\{|s_{i}^{(t)}\rangle: i\in\{1,\ldots, n\} t\in\{1,\ldots, T\} \big\} \in \{|0\rangle, |1\rangle, |+\rangle, |-\rangle, |i+\rangle, |i-\rangle\}.
#
# Each of the :math:`|s_i^{(t)}\rangle` provides us with classical access
# to a single snapshot of the :math:`\rho` and the :math:`nT`
# measurements yield the complete snapshot :math:`S_{T}`, which requires
# just :math:`3nT` bits to be stored in classical memory. This is discussed
# in further details in our previous demo about classical shadows [#tutorial]_.
#

######################################################################
# .. figure::  /demonstrations/ml_classical_shadows/class_shadow_prep.png
#    :align: center
#    :width: 100 %
#    :alt: Preparing Classical Shadows
#


######################################################################
# To prepare a classical shadow for the ground state of the Heisenberg
# model, we simply reuse the circuit template used above and reconstruct
# a qnode using a device that performs single-shot measurements.
#

dev_oshot = qml.device("default.qubit", wires=num_qubits, shots=1)
circuit_oshot = qml.QNode(circuit, dev_oshot)


######################################################################
# Now, we define a function to build the classical shadow for the quantum
# state prepared by a given :math:`n`-qubit circuit using :math:`T`-copies
# of randomized Pauli basis measurements
#


def gen_class_shadow(circ_template, circuit_params, num_shadows, num_qubits):
    # prepare the complete set of available Pauli operators
    unitary_ops = [qml.PauliX, qml.PauliY, qml.PauliZ]
    # sample random Pauli measurements uniformly
    unitary_ensmb = np.random.randint(0, 3, size=(num_shadows, num_qubits), dtype=int)

    meas_outcomes = np.zeros((num_shadows, num_qubits))
    for ns in range(num_shadows):
        # for each snapshot, extract the Pauli basis measurement to be performed
        meas_obs = [unitary_ops[unitary_ensmb[ns, i]](i) for i in range(num_qubits)]
        # perform single shot randomized Pauli measuremnt for each qubit
        meas_outcomes[ns, :] = circ_template(circuit_params, observables=meas_obs)

    return meas_outcomes, unitary_ensmb


shadow = gen_class_shadow(circuit_oshot, psi0, 100, num_qubits)
print("First five measurement outcomes =\n", shadow[0][:5])
print("First five measurement bases =\n", shadow[1][:5])


######################################################################
# Furthermore, :math:`S_{T}` can be used to construct an approximation
# of the underlying :math:`n`-qubit state :math:`\rho` by averaging over :math:`\sigma_t`:
#
# .. math::  \sigma_T(\rho) = \frac{1}{T} \sum_{1}^{T} \big(3|s_{1}^{(t)}\rangle\langle s_1^{(t)}| - \mathbb{I}\big)\otimes \ldots \otimes \big(3|s_{n}^{(t)}\rangle\langle s_n^{(t)}| - \mathbb{I}\big)
#


def snapshot_state(meas_list, obs_list):
    # undo the rotations done for performing Pauli measurements in the specific basis
    rotations = [
        qml.Hadamard(wires=0).matrix,  # X-basis
        qml.Hadamard(wires=0).matrix @ qml.S(wires=0).inv().matrix,  # Y-basis
        qml.Identity(wires=0).matrix,
    ]  # Z-basis

    # reconstruct snapshot from local Pauli measurements
    rho_snapshot = [1]
    for meas_out, basis in zip(meas_list, obs_list):
        # preparing state |s_i><s_i| using the post measurement outcome:
        # |0><0| for 1 and |1><1| for -1
        state = np.array([[1, 0], [0, 0]]) if meas_out == 1 else np.array([[0, 0], [0, 1]])
        local_rho = 3 * (rotations[basis].conj().T @ state @ rotations[basis]) - np.eye(2)
        rho_snapshot = np.kron(rho_snapshot, local_rho)

    return rho_snapshot


def shadow_state_reconst(shadow):
    num_snapshots, num_qubits = shadow[0].shape
    meas_lists, obs_lists = shadow

    # Reconstruct the quantum state from its classical shadow 
    shadow_rho = np.zeros((2 ** num_qubits, 2 ** num_qubits), dtype=complex)
    for i in range(num_snapshots):
        shadow_rho += snapshot_state(meas_lists[i], obs_lists[i])

    return shadow_rho / num_snapshots


######################################################################
# To see how well does the reconstruction work for different value of :math:`T`,
# we look at the `fidelity <https://en.wikipedia.org/wiki/Fidelity_of_quantum_states>`_
# :math:`\mathcal{F}` of the actual quantum state with respect to the reconstructed
# quantum state from the classical shadow with :math:`T` copies. We see that on average,
# as the number of copies :math:`T` is increased, the reconstruction becomes more
# effective with average higher fidelity values (orange) and lower variance (blue)
# Eventually, in the limit :math:`T\rightarrow\infty`, the reconstruction will be exact.
#
# .. figure:: /demonstrations/ml_classical_shadows/fidel_snapshot.png
#    :align: center
#    :width: 100 %
#    :alt: Fidelity of reconstructed ground state with different shadow sizes :math:`T`
#
#    Fidelity of reconstructed ground state with different shadow sizes :math:`T`
#


######################################################################
# The reconstructed quantum state :math:`\sigma_T` can also be used to
# evaluate expectation values :math:`\text{Tr}(O\sigma_T)` for some localized
# observable :math:`O = \bigotimes_{i}^{n} P_i`, where :math:`P_i \in \{I, X, Y, Z\}`.
# However, as shown above, :math:`\sigma_T` would be only an approximation of
# actual :math:`\rho` for finite values of :math:`T`. Therefore to estimate
# :math:`\langle O \rangle` robustly, we use the median of means
# estimation. For this purpose, we split up the :math:`T` shadows into
# :math:`K` equally-sized groups and estimate the median of the mean
# value of :math:`\langle O \rangle` for each of these groups.
#


def estimate_shadow_observable(shadow, observable, k=10):
    """Estimate observable related to the quantum system using its classical shadow"""
    shadow_size, num_qubits = shadow[0].shape

    # convert Pennylane observables to indices
    map_name_to_int = {"PauliX": 0, "PauliY": 1, "PauliZ": 2}
    if isinstance(observable, (qml.PauliX, qml.PauliY, qml.PauliZ)):
        target_obs = np.array([map_name_to_int[observable.name]])
        target_locs = np.array([observable.wires[0]])
    else:
        target_obs = np.array([map_name_to_int[o.name] for o in observable.obs])
        target_locs = np.array([o.wires[0] for o in observable.obs])

    # perform median of means to return the result
    means = []
    meas_list, obs_lists = shadow
    for i in range(0, shadow_size, shadow_size // k):
        meas_list_k, obs_lists_k = (
            meas_list[i : i + shadow_size // k],
            obs_lists[i : i + shadow_size // k],
        )
        indices = np.all(obs_lists_k[:, target_locs] == target_obs, axis=1)
        if sum(indices):
            means.append(
                np.sum(np.prod(meas_list_k[indices][:, target_locs], axis=1)) / sum(indices)
            )
        else:
            means.append(0)

    return np.median(means)


######################################################################
# Now, let us try to estimate the correlation matrix :math:`C^{\prime}` from the
# classical shadow of our Heisenberg model this time.
#

coups = list(it.product(range(num_qubits), repeat=2))
corrs = [corr_function_op(i, j) for i, j in coups]
qbobs = [x for sublist in corrs for x in sublist]
expval_estmt = np.zeros((num_qubits, num_qubits))

shadow = gen_class_shadow(circuit_oshot, psi0, 1000, num_qubits)

failure_rate = 1.0
k = int(2 * np.log(2 * len(qbobs) / failure_rate))

for i, j in coups:
    corrs = corr_function_op(i, j)
    if i == j:
        expval_estmt[i][j] = 1.0
    else:
        expval_estmt[i][j] = (
            np.sum(np.array([estimate_shadow_observable(shadow, o, k=k + 1) for o in corrs]))
            / 3
        )
        expval_estmt[j][i] = expval_estmt[i][j]

#########################################################################
# This time, let us visualize the deviation observed between the exact correlation
# matrix (:math:`C`) and the estimated correlation matrix (:math:`C^{\prime}`).
#

fig, ax = plt.subplots(1, 1, figsize=(6, 6))
im = ax.imshow(expval_exact-expval_estmt, cmap=plt.get_cmap("RdBu"), vmin=-1, vmax=1)
ax.xaxis.set_ticks(range(num_qubits))
ax.yaxis.set_ticks(range(num_qubits))
ax.xaxis.set_tick_params(labelsize=18)
ax.yaxis.set_tick_params(labelsize=18)
ax.set_title("Error in Estimating Correlation Matrix", fontsize=16)

bar = fig.colorbar(im, pad=0.05, shrink=0.82)
bar.set_label(r"$\Delta C_{ij}$", fontsize=18, rotation=0)
bar.ax.tick_params(labelsize=14)
plt.show()



######################################################################
# Training Classical Machine Learning Models
# ------------------------------------------
#


######################################################################
# There are multiple ways in which we can combine classical shadows and
# classical machine learning. This could include training a model to learn
# the classical representation of quantum systems based on some system
# parameter, estimating a property from such learned classical representations,
# or a combination of both. In our case, we consider the problem of using
# infinite-width neural networks to learn the ground-state representation of the
# Heisenberg model Hamiltonian :math:`H(x_l)` from the coupling vector :math:`x_l`, 
# where :math:`x_l = [J_{i,j} \text{ for } i < j]` and predict the correlation
# functions :math:`C_{ij}`:
#
# .. math::  \big\{x_l \rightarrow \sigma_T(\rho(x_l)) \rightarrow \text{Tr}(\hat{C}_{ij} \sigma_T(\rho(x_l))) \big\}_{l=1}^{N}
#
# Using the theory of infinite-width neural networks [#neurtangkernel]_, we
# consider the following machine learning models:
#
# .. math::  \hat{\sigma}_{N} (x) = \sum_{l=1}^{N} \kappa(x, x_l)\sigma_T (x_l) = \sum_{l=1}^{N} \left(\sum_{l^{\prime}=1}^{N} k(x, x_{l^{\prime}})(K+\lambda I)^{-1}_{l, l^{\prime}} \sigma_T(x_l) \right),
#
# where :math:`\lambda > 0` is a regularization parameter in cases when
# :math:`K` is not invertible, :math:`\sigma_T(x_l)` denotes the classical
# representation of the ground state :math:`\rho(x_l)` of the Heisenberg
# model constructed using :math:`T` randomized Pauli measurements and
# :math:`K_{ij}=k(x_i, x_j)` is the kernel matrix with
# :math:`k(x, x^{\prime})` as the kernel function.
#
# Similarly, estimating an expectation value on the predicted ground state
# :math:`\sigma_T(x_l)` using the trained ML model can then be done by
# evaluating:
#
# .. math::  \text{Tr}(\hat{O} \hat{\sigma}_{N} (x)) = \sum_{l=1}^{N} \kappa(x, x_l)\text{Tr}(O\sigma_T (x_l)).
#
# We train the classical kernel-based ML models using :math:`N = 70`
# randomly chosen value of coupling matrices :math:`J` with
# :math:`J_{ij} \in [0, 2]` for predicting the correlation functions
# :math:`C_{ij}`.
#

# imports for ML methods and techniques
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn import svm
from sklearn.kernel_ridge import KernelRidge

######################################################################
# First, to build the dataset, we use the function ``build_dataset`` that
# takes as input the size of the dataset (``num_points``), the topology of
# the lattice (:math:`Nr` and :math:`Nc`) and the number of randomized
# Pauli measurements (T) for construction of classical shadows. The
# ``X_data`` is the set of coupling vectors which are defined as a
# stripped version of coupling matrix :math:`J`, where only non-duplicate
# and non-zero :math:`J_{ij}` are considered. The ``y_exact`` and
# ``y_clean`` are the set of correlation vectors, i.e., the flattened
# correlation matrix :math:`C`, computed with respect to ground-state
# obtained from exact diagonalization and classical shadow representation
# (with :math:`T=500`), respectively.
#


def build_dataset(num_points, Nr, Nc, T=500):
    """Builds dataset for Heisenberg model: X (coupling vector), y (correlation matrix)"""

    num_qubits = Nr * Nc
    X, y_exact, y_estim = [], [], []
    coupling_mats = build_coupling_mats(num_points, Nr, Nc)

    for coupling_mat in coupling_mats:

        ham = Hamiltonian(coupling_mat)

        psi = np.zeros(2 ** num_qubits)
        if len(ham.ops):  # Sanity Check
            eigvals, eigvecs = sp.sparse.linalg.eigs(qml.utils.sparse_hamiltonian(ham))
            psi = eigvecs[:, np.argmin(eigvals)]

        shadow = gen_class_shadow(circuit_oshot, psi, T, num_qubits)

        coups = list(it.product(range(num_qubits), repeat=2))
        corrs = [corr_function_op(i, j) for i, j in coups]
        qbobs = [x for sublist in corrs for x in sublist]

        failure_rate = 1
        k = int(2 * np.log(2 * len(qbobs) / failure_rate))
        expval_exact = np.zeros((num_qubits, num_qubits))
        expval_estim = np.zeros((num_qubits, num_qubits))
        for i, j in coups:
            corrs = corr_function_op(i, j)
            if i == j:
                expval_exact[i][j], expval_estim[i][j] = 1.0, 1.0
            else:
                expval_exact[i][j] = (
                    np.sum(np.array([circuit_exact(psi, observables=[o]) for o in corrs]).T)
                    / 3
                )
                expval_estim[i][j] = (
                    np.sum(
                        np.array(
                            [estimate_shadow_observable(shadow, o, k=k + 1) for o in corrs]
                        )
                    )
                    / 3
                )
                expval_exact[j][i], expval_estim[j][i] = expval_exact[i][j], expval_estim[i][j]

        coupling_vec = []
        for coup in coupling_mat.reshape(1, -1)[0]:
            if coup and coup not in coupling_vec:
                coupling_vec.append(coup)
        coupling_vec = np.array(coupling_vec) / np.linalg.norm(coupling_vec)

        X.append(coupling_vec)
        y_exact.append(expval_exact.reshape(1, -1)[0])
        y_estim.append(expval_estim.reshape(1, -1)[0])

    return np.array(X), np.array(y_exact), np.array(y_estim)


X, y_exact, y_estim = build_dataset(100, Nr, Nc, 500)

X_data, y_data = X, y_exact
X_data.shape, y_data.shape, y_exact.shape


######################################################################
# Now that we have our dataset ready. We shift our focus to the ML models.
# Here, we use a set of three different Kernel functions: (i) Gaussian
# Kernel, (ii) Dirichlet Kernel and (iii) Neural Tangent Kernel. For all
# three of them, we consider the regularization parameter :math:`\lambda`
# from the following set:
#
# .. math::  \lambda = \left\{ 0.0025, 0.0125, 0.025, 0.05, 0.125, 0.25, 0.5, 1.0, 5.0, 10.0 \right\}
#
# Next, we define the kernel functions :math:`k(x, x^{\prime})` for each
# of the mentioned kernels:
#


######################################################################
# .. math::  k(x, x^{\prime}) = e^{-\gamma||x - x^{\prime}||^{2}_{2}} \tag{Gaussian Kernel}
#
# For Gaussian kernel, the hyperparameter
# :math:`\gamma = N^{2}/\sum_{i=1}^{N} \sum_{j=1}^{N} ||x_i-x_j||^{2}_{2} > 0`
# is chosen to be the inverse of the average Euclidean distance
# :math:`x_i` and :math:`x_j` and the kernel is implemented using the
# Radial-basis function (rbf) kernel in the ``sklearn`` library.
#


######################################################################
# .. math::  k(x, x^{\prime}) = \sum_{i\neq j}\sum_{k_i=-3}^{3}\sum_{k_j=-3}^{3} \cos{\big(\pi(k_i(x_i-x_i^{\prime}) + k_j(x_j-x_j^{\prime}))\big)} \tag{Dirichlet Kernel}
# 
# Dirichlet kernel is motivated by writing the :math:`\text{k}^{th}`
# partial sum of the Fourier series of any function :math:`f` with
# period :math:`2\pi` as a convolution. Here, we build this kernel
# as ``kernel_dirichlet`` for :math:`k=7` as defined above.
#

## Dirichlet kernel ##
kernel_dirichlet = np.zeros((X_data.shape[0], 7 * X_data.shape[1]))
for idx in range(len(X_data)):
    for k in range(len((X_data[idx]))):
        for k1 in range(-3, 4):
            kernel_dirichlet[idx, 7 * k + k1 + 3] += np.cos(np.pi * k1 * X_data[idx][k])


######################################################################
# .. math::  k(x, x^{\prime}) = k^{\text{NTK}}(x, x^{\prime}) \tag{Neural Tangent Kernel}
#
# The neural tangent kernel :math:`k^{\text{NTK}}` used here is equivalent
# to an infinite-width feed-forward neural network with four hidden
# layers and that uses the rectified linear unit (ReLU) as the activation
# function. This is implemented using the ``neural_tangents`` library.
#

## Neural tangent kernel ##
from neural_tangents import stax
init_fn, apply_fn, kernel_fn = stax.serial(
    stax.Dense(32),
    stax.Relu(),
    stax.Dense(32),
    stax.Relu(),
    stax.Dense(32),
    stax.Relu(),
    stax.Dense(32),
    stax.Relu(),
    stax.Dense(1),
)
kernel_NN = kernel_fn(X_data, X_data, "ntk")

for i in range(len(kernel_NN)):
    for j in range(len(kernel_NN)):
        kernel_NN[i][j] /= (kernel_NN[i][i] * kernel_NN[j][j]) ** 0.5


######################################################################
# From the three defined kernel methods, to obtain the best ML model, we
# perform hyperparameter tuning using cross-validation for the prediction
# task of each :math:`C_{ij}`. For this purpose, we implement the function
# ``fit_predict_data``, which takes input as the correlation function
# index ``cij``, kernel matrix ``kernel`` and internal kernel mapping
# ``opt`` required by Epsilon-Support Vector and Kernel-Ridge Regressions
# functions from ``sklearn`` library.
#


def fit_predict_data(cij, kernel, opt="linear"):
    # perform instance-wise normalization to get k(x, x')
    for idx in range(len(kernel)):
        kernel[idx] /= np.linalg.norm(kernel[idx])

    # training data (estimated from measurement data)
    y = np.array([y_estim[i][cij] for i in range(len(X_data))])
    X_train, X_test, y_train, y_test = train_test_split(
        kernel, y, test_size=0.3, random_state=24
    )

    # testing data (exact expectation values)
    y_clean = np.array([y_exact[i][cij] for i in range(len(X_data))])
    _, _, _, y_test_clean = train_test_split(kernel, y_clean, test_size=0.3, random_state=24)

    # hyperparameter tuning with cross validation
    models = [
        # Epsilon-Support Vector Regression
        (lambda Cx: svm.SVR(kernel=opt, C=Cx, epsilon=0.1)),
        # Kernel-Ridge based Regression
        (lambda Cx: KernelRidge(kernel=opt, alpha=1 / (2 * Cx))),
    ]
    hyperparams = [
        0.0025,
        0.0125,
        0.025,
        0.05,
        0.125,
        0.25,
        0.5,
        1.0,
        5.0,
        10.0,
    ]  # Regularization parameter
    best_model, best_pred, best_cv_score, best_test_score = None, None, np.inf, np.inf
    for model in models:
        for hyperparam in hyperparams:
            cv_score = -np.mean(
                cross_val_score(
                    model(hyperparam),
                    X_train,
                    y_train,
                    cv=5,
                    scoring="neg_root_mean_squared_error",
                )
            )
            if best_cv_score > cv_score:
                best_model = model(hyperparam).fit(X_train, y_train)
                best_pred = best_model.predict(X_test)
                best_cv_score = cv_score
                best_test_score = np.linalg.norm(
                    best_model.predict(X_test).ravel() - y_test_clean.ravel()
                ) / (len(y_test) ** 0.5)

    return (
        best_model,
        best_pred,
        y_test_clean,
        np.round(best_cv_score, 5),
        np.round(best_test_score, 5),
    )


######################################################################
# We perform the fitting and prediction for each :math:`C_{ij}` and print
# the output in a tabular format.
#

kernel_list = ["Gaussian kernel", "Dirichlet kernel", "Neural Tangent kernel"]
kernel_data = np.zeros((num_qubits ** 2, len(kernel_list), 2))
y_predclean, y_predicts1, y_predicts2, y_predicts3 = [], [], [], []

for cij in range(num_qubits ** 2):
    clf, y_predict, y_clean, cv_score, test_score = fit_predict_data(cij, X_data, opt="rbf")
    y_predclean.append(y_clean)
    kernel_data[cij][0] = (cv_score, test_score)
    y_predicts1.append(y_predict)
    clf, y_predict, y_clean, cv_score, test_score = fit_predict_data(cij, kernel_dirichlet)
    kernel_data[cij][1] = (cv_score, test_score)
    y_predicts2.append(y_predict)
    clf, y_predict, y_clean, cv_score, test_score = fit_predict_data(cij, kernel_NN)
    kernel_data[cij][2] = (cv_score, test_score)
    y_predicts3.append(y_predict)


# For each C_ij print (best_cv_score, test_score) pair
row_format = "{:>10}{:>22}{:>23}{:>25}"
print(row_format.format("", *kernel_list))
for idx, data in enumerate(kernel_data):
    print(
        row_format.format(
            f"C_{idx//num_qubits}{idx%num_qubits} \t| ",
            str(data[0]),
            str(data[1]),
            str(data[2]),
        )
    )


######################################################################
# Overall, we find that the model with Gaussian kernel performed the best,
# while the Dirichlet kernel one performed the worst for predicting the
# expectation value of the correlation function :math:`C_{ij}` for the
# ground state of the Heisenberg model. However, the best choice of
# :math:`\lambda` differed substantially across the different
# :math:`C_{ij}` for all the kernels. This means that no particular choice
# of the hyperparameter :math:`\lambda` could perform better than others
# at an average. We present the predicted correlation matrix
# :math:`C^{\prime}` for randomly selected Heisenberg models from the test
# set below for comparison against the actual correlation matrix
# :math:`C`, which is obtained from the ground state found using exact
# diagonalization.
#

fig, axes = plt.subplots(3, 4, figsize=(18, 14))
corr_vals = [y_predclean, y_predicts1, y_predicts2, y_predicts3]
plt_plots = [1, 14, 25]

cols = [
    "From {}".format(col)
    for col in [
        "Exact Diagnalization",
        "Gaussian Kernel",
        "Dirichlet Kernel",
        "Neur. Tang. Kernel",
    ]
]
rows = ["Model {}".format(row) for row in plt_plots]

for ax, col in zip(axes[0], cols):
    ax.set_title(col, fontsize=18)

for ax, row in zip(axes[:, 0], rows):
    ax.set_ylabel(row, rotation=90, fontsize=24)

for itr in range(3):
    for idx, corr_val in enumerate(corr_vals):
        shw = axes[itr][idx].imshow(
            np.array(corr_vals[idx]).T[plt_plots[itr]].reshape(Nr * Nc, Nr * Nc),
            cmap=plt.get_cmap("RdBu"),
            vmin=-1,
            vmax=1,
        )
        axes[itr][idx].xaxis.set_ticks(range(Nr * Nc))
        axes[itr][idx].yaxis.set_ticks(range(Nr * Nc))
        axes[itr][idx].xaxis.set_tick_params(labelsize=18)
        axes[itr][idx].yaxis.set_tick_params(labelsize=18)

fig.subplots_adjust(right=0.88)
cbar_ax = fig.add_axes([0.90, 0.15, 0.015, 0.72])
bar = fig.colorbar(shw, cax=cbar_ax)

bar.set_label(r"$C_{ij}$", fontsize=18, rotation=0)
bar.ax.tick_params(labelsize=16)
plt.show()


######################################################################
# Finally, we also attempt to showcase the effect of the size of training data
# :math:`N` and the number of Pauli measurements :math:`T`. For this, we look
# at the average value of ``best_cv_score`` for each mode, which gives us the
# root-mean-square error (RMSE) for predicting :math:`C_ij`. Here, the first
# plot looks at the different training sizes :math:`N` with a fixed number of
# randomized Pauli measurements :math:`T=100`. In contrast, the second plot
# looks at the different shadow sizes :math:`T` with a fixed training data size
# :math:`N=70`. In both cases, the performance improvement saturates after a
# sufficient increase in :math:`N` and :math:`T` values for all three kernels.
#


######################################################################
# .. image::  /demonstrations/ml_classical_shadows/rmse_shadow.png
#     :width: 47 %
# .. image::  /demonstrations/ml_classical_shadows/rmse_training.png
#     :width: 47 %
#
# Predicting two-point correlation functions for ground state of
# 2D antiferromagnetic Heisenberg model over different training size :math:`N`
# and different shadow size :math:`T`.


######################################################################
# .. _ml_classical_shadow_references:
#
# References
# ----------
#
# .. [#preskill]
#
#    H. Y. Huang, R. Kueng, G. Torlai, V. V. Albert, J. Preskill, "Provably
#    efficient machine learning for quantum many-body problems",
#    `arXiv:2106.12627 [quant-ph] <https://arxiv.org/abs/2106.12627>`__ (2021)
# 
# .. [#tutorial]
#
#    R. Wiersema & B. Doolittle, `"Classical Shadows"
#    <https://pennylane.ai/qml/demos/tutorial_classical_shadows.html>`__ (2021)
#
# .. [#neurtangkernel]
#
#    A. Jacot, F. Gabriel, and C. Hongler. "Neural tangent kernel:
#    Convergence and generalization in neural networks". `NeurIPS, 8571–8580
#    <https://proceedings.neurips.cc/paper/2018/file/5a4be1fa34e62bb8a6ec6b91d2462f5a-Paper.pdf>`__ (2018)
#