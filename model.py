from pyomo.environ import *
import datetime

# Parameters
total_days = 365  # Total days in a year
PTO_days = 15  # Available PTO days
holidays = [datetime.date(2024, 1, 1), datetime.date(2024, 7, 4), datetime.date(2024, 12, 25)]  # Example holidays
floating_holiday_days = 1  # Number of floating holidays allowed

# Create a Pyomo model
model = ConcreteModel()

# Sets
model.DAYS = RangeSet(1, total_days)

# Parameters
model.is_weekend = Param(model.DAYS, initialize=lambda model, d: (datetime.date(2024, 1, 1) + datetime.timedelta(days=d-1)).weekday() >= 5)
model.is_holiday = Param(model.DAYS, initialize=lambda model, d: datetime.date(2024, 1, 1) + datetime.timedelta(days=d-1) in holidays)

# Decision Variables
model.pto = Var(model.DAYS, within=Binary)
model.floating_holiday = Var(model.DAYS, within=Binary)

# Constraints
model.PTO_limit = Constraint(expr=sum(model.pto[d] for d in model.DAYS) <= PTO_days)
model.Floating_holiday_limit = Constraint(expr=sum(model.floating_holiday[d] for d in model.DAYS) == floating_holiday_days)
model.No_double_holiday = Constraint(model.DAYS, rule=lambda model, d: model.pto[d] + model.floating_holiday[d] <= 1)

# Auxiliary variable to keep track of non-working days
model.non_working_day = Var(model.DAYS, within=Binary)

# # Non-working days calculation
# def non_working_day_rule(model, d):
#     return model.non_working_day[d] == 1 - (model.is_weekend[d] == 0 and model.is_holiday[d] == 0 and model.pto[d] == 0 and model.floating_holiday[d] == 0)

# model.non_working_day_constraint = Constraint(model.DAYS, rule=non_working_day_rule)

# Objective: Maximize the number of consecutive non-working days
model.objective = Objective(expr=sum(model.non_working_day[d] for d in model.DAYS), sense=maximize)

# Solve the model
solver = SolverFactory('glpk')
result = solver.solve(model)

# Display results
PTO_days_taken = [d for d in model.DAYS if model.pto[d].value == 1]
floating_holiday_taken = [d for d in model.DAYS if model.floating_holiday[d].value == 1]
total_non_working_days = sum(model.non_working_day[d].value for d in model.DAYS)

print("PTO days taken:", PTO_days_taken)
print("Floating holiday taken:", floating_holiday_taken)
print("Total non-working days:", total_non_working_days)
