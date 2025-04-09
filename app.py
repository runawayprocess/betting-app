import os
from flask import Flask, request, render_template, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv

# Load environment variables from keys.env
load_dotenv("keys.env")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "fallback-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///fallback.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ----------------------
# Database Models
# ----------------------
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    venmo_handle = db.Column(db.String(50), unique=True, nullable=False)
    balance = db.Column(db.Float, default=0.0)

    def __repr__(self):
        return f"<User {self.venmo_handle} - Balance: {self.balance:.2f}>"

class Match(db.Model):
    __tablename__ = "matches"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    competitor1 = db.Column(db.String(100), nullable=False)
    competitor2 = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default="open")  # "open", "closed", "resolved"
    winner = db.Column(db.String(100), nullable=True)

    def __repr__(self):
        return f"<Match {self.name}: {self.competitor1} vs {self.competitor2} - {self.status}>"

class Bet(db.Model):
    __tablename__ = "bets"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    match_id = db.Column(db.Integer, db.ForeignKey("matches.id"), nullable=False)
    competitor_chosen = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f"<Bet on Match {self.match_id} by User {self.user_id}: ${self.amount} on {self.competitor_chosen}>"

# ----------------------
# Public Routes
# ----------------------

# Registration (entry page with donation instructions)
@app.route("/", methods=["GET", "POST"])
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        venmo_handle = request.form.get("venmo_handle")
        if not venmo_handle:
            flash("Please enter your Venmo handle.")
            return redirect(url_for("register"))
        
        existing_user = User.query.filter_by(venmo_handle=venmo_handle).first()
        if existing_user:
            flash("This Venmo handle is already registered. Please use it to log in.")
            return redirect(url_for("login"))
        
        new_user = User(venmo_handle=venmo_handle, balance=0.0)
        db.session.add(new_user)
        db.session.commit()
        flash("Registration successful! You can now start placing bets.")
        session["venmo_handle"] = venmo_handle
        return redirect(url_for("index"))
    
    return render_template("register.html")

# Login route for returning users
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        venmo_handle = request.form.get("venmo_handle")
        user = User.query.filter_by(venmo_handle=venmo_handle).first()
        if user:
            session["venmo_handle"] = venmo_handle
            flash("Logged in successfully!")
            return redirect(url_for("index"))
        else:
            flash("User not found. Please register first.")
            return redirect(url_for("register"))
    return render_template("login.html")

# Logout route
@app.route("/logout")
def logout():
    session.pop("venmo_handle", None)
    flash("You have been logged out.")
    return redirect(url_for("index"))

# Public Matches Page: Displays matches with "Bet Now" links (without admin controls)
@app.route("/index")
@app.route("/home")
@app.route("/matches")
def index():
    all_matches = Match.query.all()
    logged_in_handle = session.get("venmo_handle")
    user_balance = None
    if logged_in_handle:
        user_obj = User.query.filter_by(venmo_handle=logged_in_handle).first()
        if user_obj:
            user_balance = user_obj.balance

    # Compute odds and expected win probabilities.
    odds_dict = {}
    for m in all_matches:
        bets = Bet.query.filter_by(match_id=m.id).all()
        total_bet_comp1 = sum(bet.amount for bet in bets if bet.competitor_chosen == m.competitor1)
        total_bet_comp2 = sum(bet.amount for bet in bets if bet.competitor_chosen == m.competitor2)
        odds1 = 1 + (total_bet_comp2 / total_bet_comp1) if total_bet_comp1 > 0 else None
        odds2 = 1 + (total_bet_comp1 / total_bet_comp2) if total_bet_comp2 > 0 else None
        total = total_bet_comp1 + total_bet_comp2
        if total > 0:
            prob1 = (total_bet_comp1 / total) * 100
            prob2 = (total_bet_comp2 / total) * 100
        else:
            prob1, prob2 = None, None
        odds_dict[m.id] = {"odds1": odds1, "odds2": odds2, "prob1": prob1, "prob2": prob2}
    
    return render_template("index.html", 
                           matches=all_matches, 
                           logged_in_handle=logged_in_handle,
                           user_balance=user_balance,
                           odds=odds_dict)

# Betting Route: Allows a user to place a bet.
@app.route("/bet/<int:match_id>", methods=["GET", "POST"])
def place_bet(match_id):
    match = Match.query.get_or_404(match_id)
    if match.status != "open":
        flash("Betting is closed for this match.")
        return redirect(url_for("index"))
    
    logged_in_handle = session.get("venmo_handle")
    if request.method == "POST":
        venmo_handle = request.form.get("venmo_handle") or logged_in_handle
        chosen_competitor = request.form.get("competitor")
        amount_str = request.form.get("amount")
        
        user = User.query.filter_by(venmo_handle=venmo_handle).first()
        if not user:
            flash("User not registered. Please register first.")
            return redirect(url_for("register"))
        
        if chosen_competitor not in [match.competitor1, match.competitor2]:
            flash("Invalid competitor selected.")
            return redirect(url_for("place_bet", match_id=match.id))
        
        try:
            amount = float(amount_str)
            if amount <= 0:
                flash("Bet amount must be greater than zero.")
                return redirect(url_for("place_bet", match_id=match.id))
        except ValueError:
            flash("Invalid bet amount.")
            return redirect(url_for("place_bet", match_id=match.id))
        
        new_bet = Bet(user_id=user.id, match_id=match.id,
                      competitor_chosen=chosen_competitor, amount=amount)
        db.session.add(new_bet)
        db.session.commit()
        flash(f"You bet ${amount} on {chosen_competitor} for match '{match.name}'.")
        return redirect(url_for("index"))
    
    return render_template("bet.html", match=match, logged_in_handle=logged_in_handle)

# Public Balance Page: Displays all users' balances.
@app.route("/balance")
def view_balance():
    all_users = User.query.order_by(User.venmo_handle).all()
    return render_template("balance.html", users=all_users)

# CSV Export for Final Balances (Admin Only)
@app.route("/admin/export_csv", methods=["GET"])
def export_csv():
    import csv
    from io import StringIO
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Venmo Handle", "Gross Balance"])
    users = User.query.order_by(User.venmo_handle).all()
    for user in users:
        total_bets = sum(bet.amount for bet in Bet.query.filter_by(user_id=user.id).all())
        gross_balance = user.balance + total_bets
        writer.writerow([user.venmo_handle, f"{gross_balance:.2f}"])
    output.seek(0)
    return (output.getvalue(), 200,
            {"Content-Type": "text/csv", "Content-Disposition": 'attachment; filename="final_balances.csv"'})

# ----------------------
# Combined Admin Dashboard (Obscured URL)
# This page provides:
#   - Create Match form,
#   - For each match: close or resolve actions,
#   - Bet Volume data,
#   - User Balances.
# ----------------------
@app.route("/admin/export_bets", methods=["GET"])
def export_bets():
        import csv
        from io import StringIO

        output = StringIO()
        writer = csv.writer(output)
        
        # Write header row.
        writer.writerow(["Bet ID", "Venmo Handle", "Match Name", "Competitor Chosen", "Amount"])
        
        bets = Bet.query.all()
        for bet in bets:
            # Look up the associated user and match.
            user = User.query.get(bet.user_id)
            match = Match.query.get(bet.match_id)
            writer.writerow([
                bet.id,
                user.venmo_handle if user else "N/A",
                match.name if match else "N/A",
                bet.competitor_chosen,
                f"{bet.amount:.2f}"
            ])
        
        output.seek(0)
        return (
            output.getvalue(),
            200,
            {"Content-Type": "text/csv", "Content-Disposition": 'attachment; filename="all_bets.csv"'}
        )
@app.route("/adminRoheis14isdead/dashboard", methods=["GET", "POST"])
def admin_dashboard():
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "create_match":
            match_name = request.form.get("match_name")
            competitor1 = request.form.get("competitor1")
            competitor2 = request.form.get("competitor2")
            if not match_name or not competitor1 or not competitor2:
                flash("All fields are required to create a match.")
            else:
                new_match = Match(name=match_name, competitor1=competitor1, competitor2=competitor2, status="open")
                db.session.add(new_match)
                db.session.commit()
                flash(f"Match '{match_name}' created successfully!")
        
        elif action == "close_match":
            match_id = request.form.get("match_id")
            match = Match.query.get(match_id)
            if match and match.status == "open":
                match.status = "closed"
                db.session.commit()
                flash(f"Betting closed for match '{match.name}'.")
            else:
                flash("Match not found or already closed/resolved.")
        
        elif action == "resolve_match":
            match_id = request.form.get("match_id")
            winner = request.form.get("winner")
            match = Match.query.get(match_id)
            if match and match.status in ["open", "closed"]:
                if winner not in [match.competitor1, match.competitor2]:
                    flash("Invalid winner selected.")
                else:
                    bets = Bet.query.filter_by(match_id=match.id).all()
                    winning_bets = [bet for bet in bets if bet.competitor_chosen == winner]
                    losing_bets = [bet for bet in bets if bet.competitor_chosen != winner]
                    total_winning = sum(bet.amount for bet in winning_bets)
                    total_losing = sum(bet.amount for bet in losing_bets)
                    if total_winning > 0 and total_losing > 0:
                        for bet in winning_bets:
                            share = (bet.amount / total_winning) * total_losing
                            user = User.query.get(bet.user_id)
                            user.balance += share
                    match.status = "resolved"
                    match.winner = winner
                    db.session.commit()
                    flash(f"Match '{match.name}' resolved. Winner: {winner}")
            else:
                flash("Match not found or already resolved.")
        
        elif action == "resolve_draw":
            match_id = request.form.get("match_id")
            match = Match.query.get(match_id)
            if match and match.status in ["open", "closed"]:
                bets = Bet.query.filter_by(match_id=match.id).all()
                for bet in bets:
                    user = User.query.get(bet.user_id)
                    user.balance += bet.amount  # refund the bet amount
                match.status = "resolved"
                match.winner = "Draw"
                db.session.commit()
                flash(f"Match '{match.name}' resolved as a draw. All bets have been refunded.")
            else:
                flash("Match not found or already resolved.")
        
        elif action == "reopen_match":
            # This action will revert a previously resolved match so it can be re-resolved.
            match_id = request.form.get("match_id")
            match = Match.query.get(match_id)
            if match and match.status == "resolved":
                bets = Bet.query.filter_by(match_id=match.id).all()
                if match.winner == "Draw":
                    # For a draw, each bet was refunded by adding bet.amount.
                    for bet in bets:
                        user = User.query.get(bet.user_id)
                        user.balance -= bet.amount
                else:
                    # For normal resolutions, we reverse the winnings credited.
                    winning_bets = [bet for bet in bets if bet.competitor_chosen == match.winner]
                    total_winning = sum(bet.amount for bet in winning_bets)
                    losing_bets = [bet for bet in bets if bet.competitor_chosen != match.winner]
                    total_losing = sum(bet.amount for bet in losing_bets)
                    if total_winning > 0 and total_losing > 0:
                        for bet in winning_bets:
                            share = (bet.amount / total_winning) * total_losing
                            user = User.query.get(bet.user_id)
                            user.balance -= share
                # Now reopen the match by setting status to "closed" and clearing the winner.
                match.status = "closed"
                match.winner = None
                db.session.commit()
                flash(f"Match '{match.name}' has been reopened for resolution.")
            else:
                flash("Match not found or not resolved; cannot reopen.")
        return redirect(url_for("admin_dashboard"))
    
    # GET request: prepare data for the dashboard.
    matches = Match.query.all()
    bet_volume_data = []
    for m in matches:
        bets = Bet.query.filter_by(match_id=m.id).all()
        total_volume = sum(bet.amount for bet in bets)
        losses = None
        if m.status == "resolved" and m.winner and m.winner != "Draw":
            losses = sum(bet.amount for bet in bets if bet.competitor_chosen != m.winner)
        bet_volume_data.append({"match": m, "total_volume": total_volume, "losses": losses})
    
    users = User.query.order_by(User.venmo_handle).all()
    user_gross = {}
    for u in users:
        total_bets = sum(bet.amount for bet in Bet.query.filter_by(user_id=u.id).all())
        user_gross[u.id] = u.balance + total_bets
    print(matches, users, user_gross)
    return render_template("admin_dashboard.html",
                           matches=matches,
                           bet_volume_data=bet_volume_data,
                           users=users,
                           user_gross=user_gross)

@app.route("/adminRoheis14isdead/remove_invalid_bets", methods=["GET", "POST"])
def remove_invalid_bets():
    if request.method == "POST":
        handles_text = request.form.get("handles")
        if not handles_text:
            flash("Please enter at least one Venmo handle.")
            return redirect(url_for("remove_invalid_bets"))
        
        # Split the handles on commas and newlines, stripping whitespace.
        handles = [h.strip() for h in handles_text.replace(',', '\n').splitlines() if h.strip()]
        
        removed_count = 0
        for handle in handles:
            # Find the user based on a case-insensitive match of the venmo_handle.
            user = User.query.filter(User.venmo_handle.ilike(handle)).first()
            if user:
                bets_to_remove = Bet.query.filter_by(user_id=user.id).all()
                removed_count += len(bets_to_remove)
                for bet in bets_to_remove:
                    db.session.delete(bet)
        db.session.commit()
        flash(f"Removed {removed_count} bets for the specified handles.")
        return redirect(url_for("admin_dashboard"))
    
    return render_template("remove_invalid_bets.html")

# ----------------------
# Database Initialization and App Launch
# ----------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
