def _test_import():
    import numpy as np
    from scipy.optimize import minimize

    # Define the function to minimize (e.g., the Rosenbrock function)
    def rosen(x):
        """The Rosenbrock function"""
        return sum(100.0*(x[1:]-x[:-1]**2.0)**2.0 + (1-x[:-1])**2.0)

    x0 = np.array([1.2, 0.8, 1.2, 1.0]) # Initial guess
    res = minimize(rosen, x0, method='Nelder-Mead') # Use the Nelder-Mead algorithm

    print(res.x)

print("sgn hello world")
