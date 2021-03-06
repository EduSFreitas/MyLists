import json
import os
import platform
import secrets
import sys
import urllib
import requests
import time
import atexit
import dateutil

from PIL import Image
from jikanpy import Jikan
from flask_mail import Message
from MyLists.admin_views import User
from sqlalchemy import func, text, or_
from datetime import datetime, tzinfo, timedelta
from MyLists import app, db, bcrypt, mail, config
from flask_login import login_user, current_user, logout_user, login_required
from flask import render_template, url_for, flash, redirect, request, jsonify, session
from MyLists.forms import RegistrationForm, LoginForm, UpdateAccountForm, ChangePasswordForm, AddFollowForm, \
    ResetPasswordForm, ResetPasswordRequestForm
from MyLists.models import Series, SeriesList, SeriesEpisodesPerSeason, Status, ListType, SeriesGenre, SeriesNetwork, \
    Follow, Anime, AnimeList, AnimeEpisodesPerSeason, AnimeGenre, AnimeNetwork, HomePage, Movies, MoviesGenre, \
    MoviesList, MoviesProd, MoviesActors, SeriesActors, AnimeActors, UserLastUpdate, Badges


config.read('config.ini')
try:
    themoviedb_api_key = config['TheMovieDB']['api_key']
except:
    print("Config file error. Please read the README to configure the config.ini file properly. Exit.")
    sys.exit()

class simple_utc(tzinfo):
    def tzname(self, **kwargs):
        return "UTC"
    def utcoffset(self, dt):
        return timedelta(0)


@app.before_first_request
def create_user():
    db.create_all()
    if User.query.filter_by(id='1').first() is None:
        admin = User(username='admin',
                     email='admin@admin.com',
                     password=bcrypt.generate_password_hash("password").decode('utf-8'),
                     image_file='default.jpg',
                     active=True,
                     private=True,
                     registered_on=datetime.utcnow(),
                     activated_on=datetime.utcnow())
        db.session.add(admin)
        add_badges_to_db()
    refresh_db_badges()
    db.session.commit()


################################################### Anonymous routes ###################################################


@app.route("/", methods=['GET', 'POST'])
def home():
    image_error = url_for('static', filename='img/error.jpg')
    login_form = LoginForm()
    register_form = RegistrationForm()

    if login_form.validate_on_submit():
        user = User.query.filter_by(username=login_form.login_username.data).first()
        if user and not user.active:
            app.logger.info('[{}] Connexion attempt while account not activated'.format(user.id))
            flash('Your Account is not activated. Please check your e-mail address to activate your account.', 'danger')
        elif user and bcrypt.check_password_hash(user.password, login_form.login_password.data):
            login_user(user, remember=login_form.login_remember.data)
            app.logger.info('[{}] Logged in'.format(user.id))
            flash("You're now logged in. Welcome {0}".format(user.username), "success")
            next_page = request.args.get('next')
            if next_page is None:
                if user.homepage == HomePage.MYSERIESLIST:
                    return redirect(url_for('mymedialist', media_list='serieslist', user_name=current_user.username))
                elif user.homepage == HomePage.MYMOVIESLIST:
                    return redirect(url_for('mymedialist', media_list='movieslist', user_name=current_user.username))
                elif user.homepage == HomePage.MYANIMELIST:
                    return redirect(url_for('mymedialist', media_list='animelist', user_name=current_user.username))
                elif user.homepage == HomePage.ACCOUNT:
                    return redirect(url_for('account', user_name=current_user.username))
                elif user.homepage == HomePage.HALL_OF_FAME:
                    return redirect(url_for('hall_of_fame'))
                else:
                    return render_template('error.html', error_code=404, title='Error', image_error=image_error), 404
            else:
                return redirect(next_page)
        else:
            flash('Login Failed. Please check Username and Password', 'warning')
    if register_form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(register_form.register_password.data).decode('utf-8')
        user = User(username      = register_form.register_username.data,
                    email         = register_form.register_email.data,
                    password      = hashed_password,
                    registered_on = datetime.utcnow())
        db.session.add(user)
        db.session.commit()
        app.logger.info('[{}] New account registration : username = {}, email = {}'
                        .format(user.id, register_form.register_username.data, register_form.register_email.data))
        if send_register_email(user):
            flash('Your account has been created. Check your e-mail address to activate your account!', 'info')
            return redirect(url_for('home'))
        else:
            app.logger.error('[SYSTEM] Error while sending the registration email to {}'.format(user.email))
            return render_template('error.html', error_code=500, title='Error', image_error=image_error), 500
    if current_user.is_authenticated:
        user = User.query.filter_by(id=current_user.id).first()
        if user.homepage == HomePage.MYSERIESLIST:
            return redirect(url_for('mymedialist', media_list='serieslist', user_name=current_user.username))
        if user.homepage == HomePage.MYMOVIESLIST:
            return redirect(url_for('mymedialist', media_list='movieslist', user_name=current_user.username))
        elif user.homepage == HomePage.MYANIMELIST:
            return redirect(url_for('mymedialist', media_list='animelist', user_name=current_user.username))
        elif user.homepage == HomePage.ACCOUNT:
            return redirect(url_for('account', user_name=current_user.username))
        elif user.homepage == HomePage.HALL_OF_FAME:
            return redirect(url_for('hall_of_fame'))
    else:
        home_header = url_for('static', filename='img/home_header.jpg')
        home_img_1 = url_for('static', filename='img/home_img1.jpg')
        home_img_2 = url_for('static', filename='img/home_img2.jpg')
        return render_template('home.html',
                               login_form    = login_form,
                               register_form = register_form,
                               image_header  = home_header,
                               home_img_1    = home_img_1,
                               home_img_2    = home_img_2)


@app.route("/reset_password", methods=['GET', 'POST'])
def reset_password():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if send_reset_email(user):
            app.logger.info('[{}] Reset password email sent'.format(user.id))
            flash('An email has been sent with instructions to reset your password.', 'info')
            return redirect(url_for('home'))
        else:
            app.logger.error('[SYSTEM] Error while sending the reset password email to {}'.format(user.email))
            flash("There was an error while sending the reset password email. Please try again later.")
            return redirect(url_for('home'))

    return render_template('reset_password.html', title='Reset Password', form=form)


@app.route("/reset_password/<token>", methods=['GET', 'POST'])
def reset_password_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    user = User.verify_reset_token(token)
    if user is None:
        flash('That is an invalid or expired token', 'warning')
        return redirect(url_for('reset_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user.password = hashed_password
        db.session.commit()
        app.logger.info('[{}] Password reset via reset password email'.format(user.id))
        flash('Your password has been updated! You are now able to log in', 'success')
        return redirect(url_for('home'))

    return render_template('reset_passord_token.html', title='Reset Password', form=form)


@app.route("/register_account/<token>", methods=['GET'])
def register_account_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    user = User.verify_reset_token(token)
    if user is None or user.active:
        flash('That is an invalid or expired token', 'warning')
        return redirect(url_for('reset_password'))

    user.active = True
    user.activated_on = datetime.utcnow()
    db.session.commit()
    app.logger.info('[{}] Account activated'.format(user.id))
    flash('Your account has been activated.', 'success')

    return redirect(url_for('home'))


################################################# Authenticated routes #################################################


@app.route("/admin", methods=['GET', 'POST'])
@login_required
def admin():
    pass


@app.route("/logout", methods=['GET'])
@login_required
def logout():
    user = User.query.filter_by(id=current_user.id).first()
    logout_user()
    app.logger.info('[{}] Logged out'.format(user.id))

    return redirect(url_for('home'))


@app.route('/account/<user_name>', methods=['GET', 'POST'])
@login_required
def account(user_name):
    image_error = url_for('static', filename='img/error.jpg')
    user = User.query.filter_by(username=user_name).first()

    # No account with this username and protection of the admin account
    if (user is None) or (user.id == 1 and current_user.id != 1):
        return render_template('error.html', error_code=404, title='Error', image_error=image_error), 404

    # Check if the account is private or in the follow list
    follow = Follow.query.filter_by(user_id=current_user.id, follow_id=user.id).first()
    if current_user.id == user.id or current_user.id == 1:
        pass
    elif user.private and follow is None:
        return render_template('error.html', error_code=404, title='Error', image_error=image_error), 404

    # Add follows form
    follow_form = AddFollowForm()
    if follow_form.submit_follow.data and follow_form.validate():
        add_follow(follow_form.follow_to_add.data)
        return redirect(url_for('account', user_name=user_name, message="follows"))

    # Add account settings form
    settings_form = UpdateAccountForm()
    if settings_form.submit_account.data and settings_form.validate():
        if settings_form.biography.data:
            user.biography = settings_form.biography.data
            db.session.commit()
            app.logger.info('[{}] Settings updated: Biography updated'.format(user.id))
        elif settings_form.biography.data == "":
            user.biography = None
            db.session.commit()
            app.logger.info('[{}] Settings updated: Biography updated'.format(user.id))
        if settings_form.picture.data:
            picture_file = save_profile_picture(settings_form.picture.data)
            old_picture_file = user.image_file
            user.image_file = picture_file
            db.session.commit()
            app.logger.info('[{}] Settings updated: old picture file = {}, new picture file = {}'
                            .format(user.id, old_picture_file, user.image_file))
        if settings_form.username.data != user.username:
            old_username = user.username
            user.username = settings_form.username.data
            db.session.commit()
            app.logger.info('[{}] Settings updated: old username = {}, new username = {}'
                            .format(user.id, old_username, user.username))
        if settings_form.isprivate.data != user.private:
            old_value = user.private
            user.private = settings_form.isprivate.data
            db.session.commit()
            app.logger.info('[{}] Settings updated: old private mode = {}, new private mode = {}'
                            .format(user.id, old_value, settings_form.isprivate.data))

        old_value = user.homepage
        if settings_form.homepage.data == "msl":
            user.homepage = HomePage.MYSERIESLIST
        elif settings_form.homepage.data == "mml":
            user.homepage = HomePage.MYMOVIESLIST
        elif settings_form.homepage.data == "mal":
            user.homepage = HomePage.MYANIMELIST
        elif settings_form.homepage.data == "acc":
            user.homepage = HomePage.ACCOUNT
        elif settings_form.homepage.data == "hof":
            user.homepage = HomePage.HALL_OF_FAME
        db.session.commit()
        app.logger.info('[{}] Settings updated: old homepage = {}, new homepage = {}'
                        .format(user.id, old_value, settings_form.homepage.data))

        email_changed = False
        if settings_form.email.data != user.email:
            old_email = user.email
            user.transition_email = settings_form.email.data
            db.session.commit()
            app.logger.info('[{}] Settings updated : old email = {}, new email = {}'
                            .format(user.id, old_email, user.transition_email))
            email_changed = True
            if send_email_update_email(user):
                success = True
            else:
                success = False
                app.logger.error('[SYSTEM] Error while sending the email update email to {}'.format(user.email))
        if not email_changed:
            flash("Your account has been updated! ", 'success')
        else:
            if success:
                flash("Your account has been updated! Please click on the link to validate your new email address.",
                      'success')
            else:
                flash("There was an error internal error. Please contact the administrator.", 'danger')
        return redirect(url_for('account', user_name=current_user.username, message="settings"))
    elif request.method == 'GET':
        settings_form.biography.data = current_user.biography
        settings_form.username.data = current_user.username
        settings_form.email.data = current_user.email
        settings_form.isprivate.data = current_user.private

        if current_user.homepage == HomePage.MYSERIESLIST:
            settings_form.homepage.data = "msl"
        elif current_user.homepage == HomePage.MYMOVIESLIST:
            settings_form.homepage.data = "mml"
        elif current_user.homepage == HomePage.MYANIMELIST:
            settings_form.homepage.data = "mal"
        elif current_user.homepage == HomePage.ACCOUNT:
            settings_form.homepage.data = "acc"
        elif current_user.homepage == HomePage.HALL_OF_FAME:
            settings_form.homepage.data = "hof"

    # Add password change form
    password_form = ChangePasswordForm()
    if password_form.submit_password.data and password_form.validate():
        hashed_password = bcrypt.generate_password_hash(password_form.confirm_new_password.data).decode('utf-8')
        current_user.password = hashed_password
        db.session.commit()
        app.logger.info('[{}] Password updated'.format(current_user.id))
        flash('Your password has been successfully updated!', 'success')
        return redirect(url_for('account', user_name=current_user.username, message="settings"))

    # Recover the follows list
    follows_list = db.session.query(User, Follow).join(Follow, Follow.follow_id == User.id)\
        .filter(Follow.user_id == user.id).group_by(Follow.follow_id).order_by(User.username).all()

    follows_list_data = []
    for follow in follows_list:
        picture_url = url_for('static', filename='profile_pics/{}'.format(follow[0].image_file))
        follow_data = {"username": follow[0].username,
                       "user_id" : follow[0].id,
                       "picture" : picture_url}

        if follow[0].private:
            if Follow.query.filter_by(user_id=current_user.id, follow_id=follow[0].id).first() is not None \
                    or current_user.id == 1:
                follows_list_data.append(follow_data)
            elif current_user.id == follow[0].id:
                follows_list_data.append(follow_data)
        else:
            follows_list_data.append(follow_data)

    # Recover account data
    account_data = get_account_data(user, user_name, follows_list_data)

    # Recover the number of user that follows you
    followers = Follow.query.filter_by(follow_id=user.id).all()

    # Recover the last updates of your follows for the follow TAB
    last_updates = get_follows_full_last_update(user.id)

    # Recover the last updates of the follows for the overview TAB
    if user.id == current_user.id:
        overview_updates = get_follows_last_update(user.id)
    else:
        overview_updates = get_user_last_update(user.id)

    # Recover the view count of the account and the media lists
    if current_user.id != 1 and user.id != current_user.id:
        user.profile_views = user.profile_views + 1
        profile_view_count = user.profile_views
        db.session.commit()
    else:
        profile_view_count = user.profile_views
    view_count = {"profile" : profile_view_count,
                  "series"  : user.series_views,
                  "anime"   : user.anime_views,
                  "movies"  : user.movies_views}

    # Recover the user's badges
    # badges_unlocked = get_badges(user.id)[1]

    # Recover the registered date
    registered_date = user.registered_on.strftime("%d %b %Y")

    # Reload on the form TAB
    try:
        message_tab = request.args['message']
    except:
        message_tab = 'overview'

    return render_template('account.html',
                           title            = "{}'s account".format(user.username),
                           data             = account_data,
                           joined           = registered_date,
                           view_count       = view_count,
                           user_id          = str(user.id),
                           user_name        = user_name,
                           message_tab      = message_tab,
                           follow_form      = follow_form,
                           followers        = len(followers),
                           last_updates     = last_updates,
                           overview_updates = overview_updates,
                           settings_form    = settings_form,
                           password_form    = password_form,
                           user_biography   = user.biography,
                           badges_unlocked  = "")


@app.route("/badges/<user_name>", methods=['GET', 'POST'])
@login_required
def badges(user_name):
    user = User.query.filter_by(username=user_name).first()

    # Check if the user exists
    if user is None:
        image_error = url_for('static', filename='img/error.jpg')
        return render_template('error.html', error_code=404, title='Error', image_error=image_error), 404

    badges = get_badges(user.id)[0]
    return render_template('badges.html',
                           title       = "{}'s badges".format(user_name),
                           user_badges = badges)


@app.route("/level_grade_data", methods=['GET'])
@login_required
def level_grade_data():
    all_ranks_list = []
    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\\csv_data\\levels_ranks.csv")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/csv_data/levels_ranks.csv")
    with open(path, "r") as fp:
        for line in fp:
            all_ranks_list.append(line.split(";"))

    all_ranks_list.pop(0)

    i, low, incr = [0, 0, 0]
    data = []
    while True:
        rank = all_ranks_list[i][2]
        if rank == 'ReachRank49':
            data.append(["ReachRank49", "Inheritor", [147, "+"], [(20*low)*(1+low), "+"],
                         [int(((20*low)*(1+low))/60), "+"]])
            break
        for j in range(i, len(all_ranks_list)):
            if str(rank) == all_ranks_list[j][2]:
                incr += 1
            else:
                data.append([rank, all_ranks_list[j-1][3], [low, incr-1],
                             [(20*low)*(1+low), ((20*incr)*(1+incr))-1],
                             [int(((20*low)*(1+low))/60), int((((20*incr)*(1+incr))-1)/60)]])
                i = j
                low = incr
                break

    return render_template('level_grade_data.html', title='Level grade data', data=data)


@app.route("/knowledge_grade_data", methods=['GET'])
@login_required
def knowledge_grade_data():
    all_knowledge_ranks_list = []
    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\\csv_data\\knowledge_ranks.csv")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/csv_data/knowledge_ranks.csv")
    with open(path, "r") as fp:
        for line in fp:
            all_knowledge_ranks_list.append(line.split(";"))

    i, low, incr = [1, 1, 1]
    data = []
    while True:
        rank = all_knowledge_ranks_list[i][1]
        if i == 346:
            data.append(["Knowledge_Emperor_Grade_4", "Knowledge Emperor Grade 4", [345, "+"]])
            break
        for j in range(i, len(all_knowledge_ranks_list)):
            if str(rank) == all_knowledge_ranks_list[j][1]:
                incr += 1
            else:
                data.append([rank, all_knowledge_ranks_list[j - 1][2], [low-1, incr-2]])
                i = j
                low = incr
                break

    return render_template('knowledge_grade_data.html', title='Knowledge grade data', data=data)


@app.route("/email_update/<token>", methods=['GET'])
@login_required
def email_update_token(token):
    user = User.verify_reset_token(token)
    if user is None:
        flash('That is an invalid or expired token', 'warning')
        return redirect(url_for('home'))

    if str(user.id) != current_user.id:
        return redirect(url_for('home'))

    old_email = user.email
    user.email = user.transition_email
    user.transition_email = None
    db.session.commit()
    app.logger.info('[{}] Email successfully changed from {} to {}'.format(user.id, old_email, user.email))
    flash('Email successfully updated!', 'success')

    return redirect(url_for('home'))


@app.route("/hall_of_fame", methods=['GET'])
@login_required
def hall_of_fame():
    users = User.query.filter(User.id >= "2").filter_by(active=True).order_by(User.username.asc()).all()

    current_user_follows = Follow.query.filter_by(user_id=current_user.id).all()
    follows_list = []
    for follow in current_user_follows:
        follows_list.append(follow.follow_id)

    all_users_data = []
    for user in users:
        user_data = {}
        user_data["username"]        = user.username
        user_data["id"]              = user.id
        user_data["profile_picture"] = user.image_file

        series_level = get_level_and_grade(user.time_spent_series)
        user_data["series_level"]       = series_level["level"]
        user_data["series_percent"]     = series_level["level_percent"]
        user_data["series_grade_id"]    = series_level["grade_id"]
        user_data["series_grade_title"] = series_level["grade_title"]

        anime_level = get_level_and_grade(user.time_spent_anime)
        user_data["anime_level"]        = anime_level["level"]
        user_data["anime_percent"]      = anime_level["level_percent"]
        user_data["anime_grade_id"]     = anime_level["grade_id"]
        user_data["anime_grade_title"]  = anime_level["grade_title"]

        movies_level = get_level_and_grade(user.time_spent_movies)
        user_data["movies_level"]       = movies_level["level"]
        user_data["movies_percent"]     = movies_level["level_percent"]
        user_data["movies_grade_id"]    = movies_level["grade_id"]
        user_data["movies_grade_title"] = movies_level["grade_title"]

        knowledge_level = int(series_level["level"] + anime_level["level"] + movies_level["level"])
        knowledge_grade = get_knowledge_grade(knowledge_level)
        user_data["knowledge_level"]        = knowledge_level
        user_data["knowledge_grade_id"]     = knowledge_grade["grade_id"]
        user_data["knowledge_grade_title"]  = knowledge_grade["grade_title"]

        if user.id in follows_list:
            user_data["isfollowing"] = True
        else:
            user_data["isfollowing"] = False

        if user.id == current_user.id:
            user_data["isprivate"] = False
            user_data["iscurrentuser"] = True
        else:
            user_data["isprivate"] = user.private
            user_data["iscurrentuser"] = False

        all_users_data.append(user_data)

    return render_template("hall_of_fame.html",
                           title='Hall of Fame',
                           all_data=all_users_data)


@app.route("/global_stats", methods=['GET'])
@login_required
def global_stats():
    # Total time spent for each media
    times_spent = db.session.query(User, func.sum(User.time_spent_series), func.sum(User.time_spent_anime),
                             func.sum(User.time_spent_movies)).filter(User.id >= '2', User.active==True).all()

    if times_spent[0][0] is None:
        total_time = {"total": 0, "series": 0, "anime": 0, "movies": 0}
    else:
        total_time = {"total": int((times_spent[0][1]/60)+(times_spent[0][2]/60)+(times_spent[0][3]/60)),
                      "series": int(times_spent[0][1]/60),
                      "anime": int(times_spent[0][2]/60),
                      "movies": int(times_spent[0][3]/60)}

    # Top media in users' lists
    top_series = db.session.query(Series, SeriesList, func.count(SeriesList.series_id==Series.id).label("count"))\
        .join(SeriesList, SeriesList.series_id == Series.id).group_by(SeriesList.series_id)\
        .filter(SeriesList.user_id >= '2').order_by(text("count desc")).limit(5).all()
    top_anime = db.session.query(Anime, AnimeList, func.count(AnimeList.anime_id==Anime.id).label("count"))\
        .join(AnimeList, AnimeList.anime_id == Anime.id).group_by(AnimeList.anime_id)\
        .filter(AnimeList.user_id >= '2').order_by(text("count desc")).limit(5).all()
    top_movies = db.session.query(Movies, MoviesList, func.count(MoviesList.movies_id==Movies.id).label("count"))\
        .join(MoviesList, MoviesList.movies_id == Movies.id).group_by(MoviesList.movies_id)\
        .filter(MoviesList.user_id >= '2').order_by(text("count desc")).limit(5).all()

    top_all_series, top_all_anime, top_all_movies = [], [], []
    for i in range(5):
        try:
            tmp_series = {"name": top_series[i][0].name, "quantity": top_series[i][2]}
        except:
            tmp_series = {"name": "-", "quantity": "-"}
        try:
            tmp_anime = {"name": top_anime[i][0].name, "quantity": top_anime[i][2]}
        except:
            tmp_anime = {"name": "-", "quantity": "-"}
        try:
            tmp_movies = {"name": top_movies[i][0].name, "quantity": top_movies[i][2]}
        except:
            tmp_movies = {"name": "-", "quantity": "-"}

        top_all_series.append(tmp_series)
        top_all_anime.append(tmp_anime)
        top_all_movies.append(tmp_movies)

    most_present_media = {"series": top_all_series,
                          "anime": top_all_anime,
                          "movies": top_all_movies}

    # Top genre in users' lists
    series_genres = db.session.query(SeriesList, SeriesGenre, func.count(SeriesGenre.genre).label('count'))\
        .join(SeriesGenre, SeriesGenre.series_id == SeriesList.series_id)\
        .group_by(SeriesGenre.genre).filter(SeriesList.user_id >= '2').order_by(text('count desc')).limit(5).all()
    anime_genres = db.session.query(AnimeList, AnimeGenre, func.count(AnimeGenre.genre).label('count'))\
        .join(AnimeGenre, AnimeGenre.anime_id == AnimeList.anime_id)\
        .group_by(AnimeGenre.genre).filter(AnimeList.user_id >= '2').order_by(text('count desc')).limit(5).all()
    movies_genres = db.session.query(MoviesList, MoviesGenre, func.count(MoviesGenre.genre).label('count'))\
        .join(MoviesGenre, MoviesGenre.movies_id == MoviesList.movies_id)\
        .group_by(MoviesGenre.genre).filter(MoviesList.user_id >= '2').order_by(text('count desc')).limit(5).all()

    all_series_genres, all_anime_genres, all_movies_genres = [], [], []
    for i in range(5):
        try:
            tmp_series = {"genre": series_genres[i][1].genre, "quantity": series_genres[i][2]}
        except:
            tmp_series = {"genre": "-", "quantity": "-"}
        try:
            tmp_anime = {"genre": anime_genres[i][1].genre, "quantity": anime_genres[i][2]}
        except:
            tmp_anime = {"genre": "-", "quantity": "-"}
        try:
            tmp_movies = {"genre": movies_genres[i][1].genre, "quantity": movies_genres[i][2]}
        except:
            tmp_movies = {"genre": "-", "quantity": "-"}

        all_series_genres.append(tmp_series)
        all_anime_genres.append(tmp_anime)
        all_movies_genres.append(tmp_movies)

    most_genres_media = {"series": all_series_genres,
                         "anime": all_anime_genres,
                         "movies": all_movies_genres}

    # Top actors in the users' lists
    series_actors = db.session.query(SeriesList, SeriesActors, func.count(SeriesActors.name).label('count'))\
        .join(SeriesActors, SeriesActors.series_id == SeriesList.series_id)\
        .filter(SeriesActors.name != "Unknown").group_by(SeriesActors.name).filter(SeriesList.user_id >= '2')\
        .order_by(text('count desc')).limit(5).all()
    anime_actors = db.session.query(AnimeList, AnimeActors, func.count(AnimeActors.name).label('count'))\
        .join(AnimeActors, AnimeActors.anime_id == AnimeList.anime_id)\
        .filter(AnimeActors.name != "Unknown").group_by(AnimeActors.name).filter(AnimeList.user_id >= '2')\
        .order_by(text('count desc')).limit(5).all()
    movies_actors = db.session.query(MoviesList, MoviesActors, func.count(MoviesActors.name).label('count'))\
        .join(MoviesActors, MoviesActors.movies_id == MoviesList.movies_id)\
        .filter(MoviesActors.name != "Unknown").group_by(MoviesActors.name).filter(MoviesList.user_id >= '2')\
        .order_by(text('count desc')).limit(5).all()

    all_series_actors, all_anime_actors, all_movies_actors = [], [], []
    for i in range(5):
        try:
            tmp_series = {"name": series_actors[i][1].name, "quantity": series_actors[i][2]}
        except:
            tmp_series = {"name": "-", "quantity": "-"}
        try:
            tmp_anime = {"name": anime_actors[i][1].name, "quantity": anime_actors[i][2]}
        except:
            tmp_anime = {"name": "-", "quantity": "-"}
        try:
            tmp_movies = {"name": movies_actors[i][1].name, "quantity": movies_actors[i][2]}
        except:
            tmp_movies = {"name": "-", "quantity": "-"}

        all_series_actors.append(tmp_series)
        all_anime_actors.append(tmp_anime)
        all_movies_actors.append(tmp_movies)

    most_actors_media = {"series": all_series_actors,
                         "anime": all_anime_actors,
                         "movies": all_movies_actors}

    # Top dropped media in the users' lists
    series_dropped = db.session.query(Series, SeriesList, func.count(SeriesList.series_id==Series.id).label('count'))\
        .join(SeriesList, SeriesList.series_id == Series.id).filter_by(status=Status.DROPPED)\
        .group_by(SeriesList.series_id).filter(SeriesList.user_id >= '2').order_by(text('count desc')).limit(5).all()
    anime_dropped = db.session.query(Anime, AnimeList, func.count(AnimeList.anime_id==Anime.id).label('count'))\
        .join(AnimeList, AnimeList.anime_id == Anime.id).filter_by(status=Status.DROPPED).group_by(AnimeList.anime_id)\
        .filter(AnimeList.user_id >= '2').order_by(text('count desc')).limit(5).all()

    top_series_dropped, top_anime_dropped = [], []
    for i in range(5):
        try:
            tmp_series = {"name": series_dropped[i][0].name, "quantity": series_dropped[i][2]}
        except:
            tmp_series = {"name": "-", "quantity": "-"}
        try:
            tmp_anime = {"name": anime_dropped[i][0].name, "quantity": anime_dropped[i][2]}
        except:
            tmp_anime = {"name": "-", "quantity": "-"}

        top_series_dropped.append(tmp_series)
        top_anime_dropped.append(tmp_anime)

    top_dropped_media = {"series": top_series_dropped,
                         "anime": top_anime_dropped}

    # Total number of seasons/episodes watched for the series and anime
    total_series_eps_seasons = db.session.query(SeriesList, SeriesEpisodesPerSeason,
        func.group_concat(SeriesEpisodesPerSeason.episodes))\
        .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id==SeriesList.series_id)\
        .group_by(SeriesList.id).filter(SeriesList.user_id >= '2').all()
    total_anime_eps_seasons = db.session.query(AnimeList, AnimeEpisodesPerSeason,
        func.group_concat(AnimeEpisodesPerSeason.episodes))\
        .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == AnimeList.anime_id)\
        .group_by(AnimeList.id).filter(AnimeList.user_id >= '2').all()

    total_series_seas_watched = 0
    total_series_eps_watched = 0
    for element in total_series_eps_seasons:
        if element[0].status != Status.PLAN_TO_WATCH:
            episodes = element[2].split(",")
            episodes = [int(x) for x in episodes]
            if episodes[int(element[0].current_season) - 1] == int(element[0].last_episode_watched):
                total_series_seas_watched += int(element[0].current_season)
            else:
                total_series_seas_watched += int(element[0].current_season) - 1
            for i in range(1, element[0].current_season):
                total_series_eps_watched += episodes[i - 1]
            total_series_eps_watched += element[0].last_episode_watched

    total_anime_seas_watched = 0
    total_anime_eps_watched = 0
    for element in total_anime_eps_seasons:
        if element[0].status != Status.PLAN_TO_WATCH:
            episodes = element[2].split(",")
            episodes = [int(x) for x in episodes]
            if episodes[int(element[0].current_season) - 1] == int(element[0].last_episode_watched):
                total_anime_seas_watched += int(element[0].current_season)
            else:
                total_anime_seas_watched += int(element[0].current_season) - 1
            for i in range(1, element[0].current_season):
                total_anime_eps_watched += episodes[i - 1]
            total_anime_eps_watched += element[0].last_episode_watched

    total_seasons_media = {"series": total_series_seas_watched,
                           "anime": total_anime_seas_watched}
    total_episodes_media = {"series": total_series_eps_watched,
                            "anime": total_anime_eps_watched}

    return render_template("global_stats.html",
                           title='Global Stats',
                           total_time=total_time,
                           most_present_media=most_present_media,
                           most_actors_media=most_actors_media,
                           top_dropped_media=top_dropped_media,
                           total_seasons_media=total_seasons_media,
                           total_episodes_media=total_episodes_media,
                           most_genres_media=most_genres_media)


@app.route("/current_trends", methods=['GET'])
@login_required
def current_trends():
    # Trending movies
    try:
        movies_response = requests.get("https://api.themoviedb.org/3/trending/movie/week?api_key={}"
            .format(themoviedb_api_key))
    except:
        movies_response = None
    movies_trends = current_trends(movies_response, ListType.MOVIES)

    # Trending series
    try:
        series_response = requests.get("https://api.themoviedb.org/3/trending/tv/week?api_key={}"
            .format(themoviedb_api_key))
    except:
        series_response = None
    series_trends = current_trends(series_response, ListType.SERIES)

    # Trending anime
    try:
        jikan = Jikan()
        anime_response = jikan.top(type='anime', page=1, subtype='airing')
    except:
        anime_response = None
    anime_trends = current_trends(anime_response, ListType.ANIME)

    if (movies_trends == None) or (series_trends  == None) or (anime_trends == None):
        flash('Current trends are not available right now, try again later', 'warning')
        return redirect(url_for('account', user_name=current_user.username))

    return render_template("current_trends.html",
                           title         = "Current trends",
                           movies_trends = movies_trends,
                           series_trends = series_trends,
                           anime_trends  = anime_trends)


@app.route("/follow_status", methods=['POST'])
@login_required
def follow_status():
    image_error = url_for('static', filename='img/error.jpg')
    try:
        json_data = request.get_json()
        follow_id = int(json_data['follow_id'])
        status = json_data['follow_status']
    except:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Check if the follow ID exist in the User database and status is boolean
    if (User.query.filter_by(id=follow_id).first() is None) or (type(status) is not bool):
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Check the status
    if status:
        # Check if the follow already exists
        if Follow.query.filter_by(user_id=current_user.id, follow_id=follow_id).first() is not None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
        # Follow the user
        new_follow = Follow(user_id=current_user.id, follow_id=follow_id)
        db.session.add(new_follow)
        db.session.commit()
        app.logger.info('[{}] follow the user with ID {}'.format(current_user.id, follow_id))
    else:
        # Check if the user to unfollow is in the follow list
        if Follow.query.filter_by(user_id=current_user.id, follow_id=follow_id).first() is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
        # Unfollow the user
        Follow.query.filter_by(user_id=current_user.id, follow_id=follow_id).delete()
        db.session.commit()
        app.logger.info('[{}] Follow with ID {} unfollowed'.format(current_user.id, follow_id))

    return '', 204


#################################################### Media routes ######################################################


@app.route("/<media_list>/<user_name>", methods=['GET'])
@login_required
def mymedialist(media_list, user_name):
    image_error = url_for('static', filename='img/error.jpg')
    user = User.query.filter_by(username=user_name).first()

    # Check if the user exists
    if user is None:
        return render_template('error.html', error_code=404, title='Error', image_error=image_error), 404

    # Check if the current user can see the target user's list
    if current_user.id != user.id and current_user.id != 1:
        follow = Follow.query.filter_by(user_id=current_user.id, follow_id=user.id).first()
        if user.id == 1:
            return render_template('error.html', error_code=404, title='Error', image_error=image_error), 404
        if user.private:
            if follow is None:
                return render_template('error.html', error_code=404, title='Error', image_error=image_error), 404

    # Check the route and retrieve the media data
    if media_list == "serieslist":
        element_data = db.session.query(Series, SeriesList,
                                        func.group_concat(SeriesGenre.genre.distinct()),
                                        func.group_concat(SeriesNetwork.network.distinct()),
                                        func.group_concat(SeriesEpisodesPerSeason.season.distinct()),
                                        func.group_concat(SeriesActors.name.distinct()),
                                        func.group_concat(SeriesEpisodesPerSeason.episodes))\
            .join(SeriesList, SeriesList.series_id == Series.id)\
            .join(SeriesGenre, SeriesGenre.series_id == Series.id)\
            .join(SeriesNetwork, SeriesNetwork.series_id == Series.id)\
            .join(SeriesActors, SeriesActors.series_id == Series.id)\
            .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id == Series.id)\
            .filter(SeriesList.user_id == user.id).group_by(Series.id).order_by(Series.name.asc()).all()
        covers_path = url_for('static', filename='covers/series_covers/')
        media_all_data = get_all_media_data(element_data, ListType.SERIES, covers_path, user.id)
    elif media_list == "animelist":
        element_data = db.session.query(Anime, AnimeList,
                                        func.group_concat(AnimeGenre.genre.distinct()),
                                        func.group_concat(AnimeNetwork.network.distinct()),
                                        func.group_concat(AnimeEpisodesPerSeason.season.distinct()),
                                        func.group_concat(AnimeActors.name.distinct()),
                                        func.group_concat(AnimeEpisodesPerSeason.episodes))\
            .join(AnimeList, AnimeList.anime_id == Anime.id)\
            .join(AnimeGenre, AnimeGenre.anime_id == Anime.id)\
            .join(AnimeNetwork, AnimeNetwork.anime_id == Anime.id)\
            .join(AnimeActors, AnimeActors.anime_id == Anime.id)\
            .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == Anime.id)\
            .filter(AnimeList.user_id == user.id).group_by(Anime.id).order_by(Anime.name.asc()).all()
        covers_path = url_for('static', filename='covers/anime_covers/')
        media_all_data = get_all_media_data(element_data, ListType.ANIME, covers_path, user.id)
    elif media_list == "movieslist":
        element_data = db.session.query(Movies, MoviesList,
                                        func.group_concat(MoviesGenre.genre.distinct()),
                                        func.group_concat(MoviesProd.production_company.distinct()),
                                        func.group_concat(MoviesActors.name.distinct()))\
            .join(MoviesList, MoviesList.movies_id == Movies.id)\
            .join(MoviesGenre, MoviesGenre.movies_id == Movies.id)\
            .join(MoviesProd, MoviesProd.movies_id == Movies.id)\
            .join(MoviesActors, MoviesActors.movies_id == Movies.id)\
            .filter(MoviesList.user_id == user.id).group_by(Movies.id).order_by(Movies.name.asc()).all()
        covers_path = url_for('static', filename='covers/movies_covers/')
        media_all_data = get_all_media_data(element_data, ListType.MOVIES, covers_path, user.id)
    else:
        return render_template('error.html', error_code=404, title='Error', image_error=image_error), 404

    # View count of the media lists
    if current_user.id != 1 and user.id != current_user.id:
        if media_list == "serieslist":
            user.series_views = user.series_views + 1
        elif media_list == "animelist":
            user.anime_views = user.anime_views + 1
        elif media_list == "movieslist":
            user.movies_views = user.movies_views + 1
        db.session.commit()

    if media_list == "serieslist" or media_list == "animelist":
        return render_template('mymedialist/series_anime_list.html',
                               title            = "{}'s {}".format(user_name, media_list),
                               all_data         = media_all_data["all_data"],
                               common_elements  = media_all_data["common_elements"],
                               media_list       = media_list,
                               target_user_name = user_name,
                               target_user_id   = str(user.id))
    elif media_list == "movieslist":
        return render_template('mymedialist/movieslist.html',
                               title            = "{}'s {}".format(user_name, media_list),
                               all_data         = media_all_data["all_data"],
                               common_elements  = media_all_data["common_elements"],
                               media_list       = media_list,
                               target_user_name = user_name,
                               target_user_id   = str(user.id))


@app.route('/update_element_season', methods=['POST'])
@login_required
def update_element_season():
    image_error = url_for('static', filename='img/error.jpg')
    try:
        json_data = request.get_json()
        season = int(json_data['season'])
        element_id = int(json_data['element_id'])
        element_type = json_data['element_type']
    except:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Check if the list type is correct
    valide_types = ["animelist", "serieslist"]
    if element_type not in valide_types:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Check if the element exists
    if element_type == "animelist":
        anime = Anime.query.filter_by(id=element_id).first()
        if anime is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
    elif element_type == "serieslist":
        series = Series.query.filter_by(id=element_id).first()
        if series is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Check if the element is in the current user's list
    if element_type == "animelist":
        if AnimeList.query.filter_by(user_id=current_user.id, anime_id=element_id).first() is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
    elif element_type == "serieslist":
        if SeriesList.query.filter_by(user_id=current_user.id, series_id=element_id).first() is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Check if the season number is between 1 and <last_season>
    if element_type == "animelist":
        last_season = AnimeEpisodesPerSeason.query.filter_by(anime_id=element_id)\
            .order_by(AnimeEpisodesPerSeason.season.desc()).first().season
        if (season+1 < 1) or (season+1 > last_season):
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

        update = AnimeList.query.filter_by(anime_id=element_id, user_id=current_user.id).first()
        old_season = update.current_season
        old_episode = update.last_episode_watched
        update.current_season = season + 1
        update.last_episode_watched = 1
        db.session.commit()
        app.logger.info("[{}] Anime season with ID {} updated: {}".format(current_user.id, element_id, season+1))
        set_last_update(media_name=anime.name, media_type=ListType.ANIME, old_season=old_season,
                        new_season=update.current_season, old_episode=old_episode, new_episode=1)
    elif element_type == "serieslist":
        last_season = SeriesEpisodesPerSeason.query.filter_by(series_id=element_id)\
            .order_by(SeriesEpisodesPerSeason.season.desc()).first().season
        if (season+1 < 1) or (season+1 > last_season):
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

        update = SeriesList.query.filter_by(series_id=element_id, user_id=current_user.id).first()
        old_season = update.current_season
        old_episode = update.last_episode_watched
        update.current_season = season + 1
        update.last_episode_watched = 1
        db.session.commit()
        app.logger.info('[{}] Series season with ID {} updated: {}'.format(current_user.id, element_id, season+1))
        set_last_update(media_name=series.name, media_type=ListType.SERIES, old_season=old_season,
                        new_season=update.current_season, old_episode=old_episode, new_episode=1)

    # Compute total time spent
    if element_type == "animelist":
        compute_media_time_spent(ListType.ANIME)
    elif element_type == "serieslist":
        compute_media_time_spent(ListType.SERIES)

    return '', 204


@app.route('/update_element_episode', methods=['POST'])
@login_required
def update_element_episode():
    image_error = url_for('static', filename='img/error.jpg')
    try:
        json_data = request.get_json()
        episode = int(json_data['episode'])
        element_id = int(json_data['element_id'])
        element_type = json_data['element_type']
    except:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    valid_element_type = ["animelist", "serieslist"]
    if element_type not in valid_element_type:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Check if the element exists
    if element_type == "animelist":
        anime = Anime.query.filter_by(id=element_id).first()
        if anime is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
    elif element_type == "serieslist":
        series = Series.query.filter_by(id=element_id).first()
        if series is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Check if the element is in the current user's list
    if element_type == "animelist":
        if AnimeList.query.filter_by(user_id=current_user.id, anime_id=element_id).first() is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
    elif element_type == "serieslist":
        if SeriesList.query.filter_by(user_id=current_user.id, series_id=element_id).first() is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Check if the episode number is between 1 and <last_episode>
    if element_type == "animelist":
        current_season = AnimeList.query.filter_by(user_id=current_user.id, anime_id=element_id).first().current_season
        last_episode = AnimeEpisodesPerSeason.query.filter_by(anime_id=element_id, season=current_season)\
            .first().episodes
        if (episode+1 < 1) or (episode+1 > last_episode):
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

        update = AnimeList.query.filter_by(anime_id=element_id, user_id=current_user.id).first()
        old_episode = update.last_episode_watched
        update.last_episode_watched = episode + 1
        db.session.commit()
        app.logger.info('[{}] Anime episode with ID {} updated: {}'.format(current_user.id, element_id, episode+1))
        set_last_update(media_name=anime.name, media_type=ListType.ANIME, old_season=update.current_season,
                        new_season=update.current_season, old_episode=old_episode,
                        new_episode=update.last_episode_watched)
    elif element_type == "serieslist":
        current_season = SeriesList.query.filter_by(user_id=current_user.id, series_id=element_id)\
            .first().current_season
        last_episode = SeriesEpisodesPerSeason.query.filter_by(series_id=element_id, season=current_season)\
            .first().episodes
        if (episode+1 < 1) or (episode+1 > last_episode):
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

        update = SeriesList.query.filter_by(series_id=element_id, user_id=current_user.id).first()
        old_episode = update.last_episode_watched
        update.last_episode_watched = episode + 1
        db.session.commit()
        app.logger.info('[{}] Series episode with ID {} updated: {}'
                        .format(current_user.id, element_id, episode+1))
        set_last_update(media_name=series.name, media_type=ListType.SERIES, old_season=update.current_season,
                        new_season=update.current_season, old_episode=old_episode,
                        new_episode=update.last_episode_watched)

    # Compute total time spent and badges
    if element_type == "animelist":
        compute_media_time_spent(ListType.ANIME)
    elif element_type == "serieslist":
        compute_media_time_spent(ListType.SERIES)

    return '', 204


@app.route('/delete_element', methods=['POST'])
@login_required
def delete_element():
    image_error = url_for('static', filename='img/error.jpg')
    try:
        json_data = request.get_json()
        element_id = int(json_data['delete'])
        element_type = json_data['element_type']
    except:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    valid_element_type = ["animelist", "serieslist", "movieslist"]
    if element_type not in valid_element_type:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Check if the element exists
    if element_type == "animelist":
        if Anime.query.filter_by(id=element_id).first() is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
    elif element_type == "serieslist":
        if Series.query.filter_by(id=element_id).first() is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
    elif element_type == "movieslist":
        if Movies.query.filter_by(id=element_id).first() is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Check if the element is in the current user's list
    if element_type == "animelist":
        if AnimeList.query.filter_by(user_id=current_user.id, anime_id=element_id).first() is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
    elif element_type == "serieslist":
        if SeriesList.query.filter_by(user_id=current_user.id, series_id=element_id).first() is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
    elif element_type == "movieslist":
        if MoviesList.query.filter_by(user_id=current_user.id, movies_id=element_id).first() is None:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Remove the element from user's list
    if element_type == "animelist":
        AnimeList.query.filter_by(anime_id=element_id, user_id=current_user.id).delete()
        db.session.commit()
        app.logger.info('[{}] Anime with ID {} deleted'.format(current_user.id, element_id))
    elif element_type == "serieslist":
        SeriesList.query.filter_by(series_id=element_id, user_id=current_user.id).delete()
        db.session.commit()
        app.logger.info('[{}] Series with ID {} deleted'.format(current_user.id, element_id))
    elif element_type == "movieslist":
        MoviesList.query.filter_by(movies_id=element_id, user_id=current_user.id).delete()
        db.session.commit()
        app.logger.info('[{}] Movie with ID {} deleted'.format(current_user.id, element_id))

    # Compute total time spent
    if element_type == "animelist":
        compute_media_time_spent(ListType.ANIME)
    elif element_type == "serieslist":
        compute_media_time_spent(ListType.SERIES)
    elif element_type == "movieslist":
        compute_media_time_spent(ListType.MOVIES)

    return '', 204


@app.route('/change_element_category', methods=['POST'])
@login_required
def change_element_category():
    image_error = url_for('static', filename='img/error.jpg')
    try:
        json_data = request.get_json()
        element_new_category = json_data['status']
        element_id = int(json_data['element_id'])
        element_type = json_data['element_type']
    except:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    if element_type == "animelist" or element_type == "serieslist":
        category_list = ["Watching", "Completed", "On Hold", "Random", "Dropped", "Plan to Watch"]
        if element_new_category not in category_list:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
    elif element_type == "movieslist":
        category_list = ["Completed", "Completed Animation", "Plan to Watch"]
        if element_new_category not in category_list:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
    else:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Check if the element is in the user's list
    if element_type == "animelist":
        element = AnimeList.query.filter_by(anime_id=element_id, user_id=current_user.id).first()
        media_type = ListType.ANIME
    elif element_type == "serieslist":
        element = SeriesList.query.filter_by(series_id=element_id, user_id=current_user.id).first()
        media_type = ListType.SERIES
    elif element_type == "movieslist":
        element = MoviesList.query.filter_by(movies_id=element_id, user_id=current_user.id).first()
        media_type = ListType.MOVIES
    if element is None:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    old_status = element.status
    if element_new_category == 'Watching':
        element.status = Status.WATCHING
    elif element_new_category == 'Completed':
        element.status = Status.COMPLETED
        # Set Season / Episode to max
        if element_type == "animelist":
            number_season = AnimeEpisodesPerSeason.query.filter_by(anime_id=element_id).count()
            number_episode = AnimeEpisodesPerSeason.query.filter_by(anime_id=element_id, season=number_season)\
                .first().episodes
            element.current_season = number_season
            element.last_episode_watched = number_episode
        elif element_type == "serieslist":
            number_season = SeriesEpisodesPerSeason.query.filter_by(series_id=element_id).count()
            number_episode = SeriesEpisodesPerSeason.query.filter_by(series_id=element_id, season=number_season)\
                .first().episodes
            element.current_season = number_season
            element.last_episode_watched = number_episode
    elif element_new_category == 'Completed Animation':
        element.status = Status.COMPLETED_ANIMATION
    elif element_new_category == 'On Hold':
        element.status = Status.ON_HOLD
    elif element_new_category == 'Random':
        element.status = Status.RANDOM
    elif element_new_category == 'Dropped':
        element.status = Status.DROPPED
    elif element_new_category == 'Plan to Watch':
        element.status = Status.PLAN_TO_WATCH
        # Set Season/Ep to 1/1
        if element_type == "animelist":
            anime = AnimeList.query.filter_by(anime_id=element_id, user_id=current_user.id).first()
            anime.current_season = 1
            anime.last_episode_watched = 1
        elif element_type == "serieslist":
            series = SeriesList.query.filter_by(series_id=element_id, user_id=current_user.id).first()
            series.current_season = 1
            series.last_episode_watched = 1

    db.session.commit()
    app.logger.info('[{}] Category of the element with ID {} ({}) changed to {}'
                    .format(current_user.id, element_id, element_type, element_new_category))

    # Compute total time spent
    if element_type == "animelist":
        anime = Anime.query.filter_by(id=element_id).first()
        set_last_update(media_name=anime.name, media_type=media_type, old_status=old_status, new_status=element.status)
        compute_media_time_spent(ListType.ANIME)
    elif element_type == "serieslist":
        series = Series.query.filter_by(id=element_id).first()
        set_last_update(media_name=series.name, media_type=media_type, old_status=old_status, new_status=element.status)
        compute_media_time_spent(ListType.SERIES)
    elif element_type == "movieslist":
        movie = Movies.query.filter_by(id=element_id).first()
        set_last_update(media_name=movie.name, media_type=media_type, old_status=old_status, new_status=element.status)
        compute_media_time_spent(ListType.MOVIES)

    return '', 204


@app.route('/add_to_medialist', methods=['POST'])
@login_required
def add_to_medialist():
    image_error = url_for('static', filename='img/error.jpg')
    try:
        json_data = request.get_json()
        add_category = json_data['add_cat']
        element_id = int(json_data['element_id'])
        element_type = json_data['media_type']
    except:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    if element_type == "animelist" or element_type == "serieslist":
        category_list = ["Watching", "Completed", "On Hold", "Random", "Dropped", "Plan to Watch"]
        if add_category not in category_list:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
    elif element_type == "movieslist":
        category_list = ["Completed", "Plan to Watch"]
        if add_category not in category_list:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
    else:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    # Check if the element is in the current user's list
    if element_type == "animelist":
        element = AnimeList.query.filter_by(anime_id=element_id, user_id=current_user.id).first()
        list_type = ListType.ANIME
    elif element_type == "serieslist":
        element = SeriesList.query.filter_by(series_id=element_id, user_id=current_user.id).first()
        list_type = ListType.SERIES
    elif element_type == "movieslist":
        element = MoviesList.query.filter_by(movies_id=element_id, user_id=current_user.id).first()
        list_type = ListType.MOVIES
    if element is not None:
        flash("This media is already in your list", "warning")
    else:
        add_element_to_user(element_id, int(current_user.id), list_type, add_category)

    return '', 204


@app.route('/add_element', methods=['POST'])
@login_required
def add_element():
    image_error = url_for('static', filename='img/error.jpg')
    try:
        json_data = request.get_json()
        element_id = int(json_data['element_id'])
        element_type = json_data['element_type']
        element_cat = json_data['element_cat']
    except:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    if element_type == "animelist":
        category_list = ["Watching", "Completed", "On Hold", "Random", "Dropped", "Plan to Watch"]
        if element_cat not in category_list:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
        add_element(element_id, ListType.ANIME, element_cat)
    elif element_type == "serieslist":
        category_list = ["Watching", "Completed", "On Hold", "Random", "Dropped", "Plan to Watch"]
        if element_cat not in category_list:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
        add_element(element_id, ListType.SERIES, element_cat)
    elif element_type == "movieslist":
        category_list = ["Completed", "Plan to Watch"]
        if element_cat not in category_list:
            return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400
        add_element(element_id, ListType.MOVIES, element_cat)
    else:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    return '', 204


@app.route('/autocomplete/<media>', methods=['GET'])
@login_required
def autocomplete(media):
    image_error = url_for('static', filename='img/error.jpg')
    try:
        search = request.args.get('q')
    except:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    if media == "animelist":
        results = autocomplete_search_element(search, ListType.ANIME)
    elif media == "serieslist":
        results = autocomplete_search_element(search, ListType.SERIES)
    elif media == "movieslist":
        results = autocomplete_search_element(search, ListType.MOVIES)
    else:
        return render_template('error.html', error_code=400, title='Error', image_error=image_error), 400

    return jsonify(matching_results=results)


###################################################### Functions #######################################################


def current_trends(response, list_type):
    if response is None:
        return None

    trending_list = []
    if list_type == ListType.MOVIES:
        global_poster_path = "http://image.tmdb.org/t/p/w300"
        try:
            trending_data = json.loads(response.text)
            tmp = trending_data["results"]
        except:
            return None

        i = 0
        for data in trending_data["results"]:
            movies = {}
            try:
                movies["title"] = data["title"]
            except:
                movies["title"] = "Unknown"

            try:
                movies["poster_path"] = global_poster_path + data["poster_path"]
            except:
                movies["poster_path"] = "static/covers/movies_covers/default.jpg"

            try:
                movies["release_date"] = datetime.strptime(data["release_date"], '%Y-%m-%d').strftime("%d %b %Y")
            except:
                movies["release_date"] = "Unknown"

            try:
                movies["overview"] = data["overview"]
            except:
                movies["overview"] = "No overview available for this movie."

            movies["tmdb_link"] = "https://www.themoviedb.org/movie/{}".format(data["id"])
            trending_list.append(movies)
            i += 1
            if i > 11: break

        return trending_list
    elif list_type == ListType.SERIES:
        global_poster_path = "http://image.tmdb.org/t/p/w300"
        try:
            trending_data = json.loads(response.text)
            tmp = trending_data["results"]
        except:
            return None

        i = 0
        for data in trending_data["results"]:
            series = {}
            try:
                series["title"] = data["name"]
            except:
                series["title"] = "Unknown"

            try:
                series["poster_path"] = global_poster_path + data["poster_path"]
            except:
                series["poster_path"] = "static/covers/movies_covers/default.jpg"

            try:
                series["first_air_date"] = datetime.strptime(data["first_air_date"], '%Y-%m-%d').strftime("%d %b %Y")
            except:
                series["first_air_date"] = "Unknown"

            try:
                series["overview"] = data["overview"]
            except:
                series["overview"] = "No overview available for this series."

            series["tmdb_link"] = "https://www.themoviedb.org/tv/{}".format(data["id"])
            trending_list.append(series)
            i += 1
            if i > 11: break

        return trending_list
    elif list_type == ListType.ANIME:
        try:
            trending_data = response
            tmp = trending_data["top"]
        except:
            return None

        i = 0
        for data in trending_data["top"]:
            anime = {}
            try:
                anime["title"] = data["title"]
            except:
                anime["title"] = "Unknown"

            try:
                anime["poster_path"] = data["image_url"]
            except:
                anime["poster_path"] = "static/covers/movies_covers/default.jpg"

            try:
                anime["first_air_date"] = dateutil.parser.parse(data["start_date"]).strftime('%d %b %Y')
            except:
                anime["first_air_date"] = "Unknown"

            try:
                anime["overview"] = data["synopsis"]
            except:
                anime["overview"] = "There is no overview from this API. " \
                                    "You can check on MyAnimeList by clicking on the title"

            anime["tmdb_link"] = data["url"]
            trending_list.append(anime)
            i += 1
            if i > 11: break

        return trending_list
    else:
        return None


def get_account_data(user, user_name, follows_list_data):
    account_data             = {}
    account_data["series"]   = {}
    account_data["movies"]   = {}
    account_data["anime"]    = {}
    account_data["id"]       = user.id
    account_data["username"] = user_name
    account_data["follows"]  = follows_list_data

    if user.id != current_user.id:
        if Follow.query.filter_by(user_id=current_user.id, follow_id=user.id).first() is None:
            account_data["isfollowing"] = False
        else:
            account_data["isfollowing"] = True

    # Recover the profile picture
    account_data["profile_picture"] = url_for('static', filename='profile_pics/{0}'.format(user.image_file))

    # Time spent in hours for all media
    account_data["series"]["time_spent_hour"] = round(user.time_spent_series/60)
    account_data["movies"]["time_spent_hour"] = round(user.time_spent_movies/60)
    account_data["anime"]["time_spent_hour"]  = round(user.time_spent_anime/60)

    # Time spent in days for all media
    account_data["series"]["time_spent_day"] = round(user.time_spent_series/1440, 2)
    account_data["movies"]["time_spent_day"] = round(user.time_spent_movies/1440, 2)
    account_data["anime"]["time_spent_day"]  = round(user.time_spent_anime/1440, 2)

    # Count media elements of each category
    series_count = get_list_count(user.id, ListType.SERIES)
    account_data["series"]["watching_count"]    = series_count["watching"]
    account_data["series"]["completed_count"]   = series_count["completed"]
    account_data["series"]["onhold_count"]      = series_count["onhold"]
    account_data["series"]["random_count"]      = series_count["random"]
    account_data["series"]["dropped_count"]     = series_count["dropped"]
    account_data["series"]["plantowatch_count"] = series_count["plantowatch"]
    account_data["series"]["total_count"]       = series_count["total"]

    anime_count = get_list_count(user.id, ListType.ANIME)
    account_data["anime"]["watching_count"]     = anime_count["watching"]
    account_data["anime"]["completed_count"]    = anime_count["completed"]
    account_data["anime"]["onhold_count"]       = anime_count["onhold"]
    account_data["anime"]["random_count"]       = anime_count["random"]
    account_data["anime"]["dropped_count"]      = anime_count["dropped"]
    account_data["anime"]["plantowatch_count"]  = anime_count["plantowatch"]
    account_data["anime"]["total_count"]        = anime_count["total"]

    movies_count = get_list_count(user.id, ListType.MOVIES)
    account_data["movies"]["completed_count"]           = movies_count["completed"]
    account_data["movies"]["completed_animation_count"] = movies_count["completed_animation"]
    account_data["movies"]["plantowatch_count"]         = movies_count["plantowatch"]
    account_data["movies"]["total_count"]               = movies_count["total"]

    # Count the total number of seen episodes for the series
    series_data = db.session.query(SeriesList, SeriesEpisodesPerSeason,
                                   func.group_concat(SeriesEpisodesPerSeason.episodes))\
        .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id == SeriesList.series_id)\
        .filter(SeriesList.user_id == user.id).group_by(SeriesList.series_id).all()

    nb_eps_watched = 0
    for element in series_data:
        if element[0].status != Status.PLAN_TO_WATCH and element[0].status != Status.RANDOM:
            episodes = element[2].split(",")
            episodes = [int(x) for x in episodes]
            for i in range(1, element[0].current_season):
                nb_eps_watched += episodes[i-1]
            nb_eps_watched += element[0].last_episode_watched
    account_data["series"]["nb_ep_watched"] = nb_eps_watched

    # Count the total number of seen episodes for the anime
    anime_data = db.session.query(AnimeList, AnimeEpisodesPerSeason,
                                      func.group_concat(AnimeEpisodesPerSeason.episodes))\
        .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == AnimeList.anime_id)\
        .filter(AnimeList.user_id == user.id).group_by(AnimeList.anime_id)

    nb_eps_watched = 0
    for element in anime_data:
        if element[0].status != Status.PLAN_TO_WATCH and element[0].status != Status.RANDOM:
            episodes = element[2].split(",")
            episodes = [int(x) for x in episodes]
            for i in range(1, element[0].current_season):
                nb_eps_watched += episodes[i-1]
            nb_eps_watched += element[0].last_episode_watched
    account_data["anime"]["nb_ep_watched"] = nb_eps_watched

    # Media percentages
    if account_data["series"]["nb_ep_watched"] == 0:
        account_data["series"]["element_percentage"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    else:
        account_data["series"]["element_percentage"] = [
            (float(account_data["series"]["watching_count"]/account_data["series"]["total_count"]))*100,
            (float(account_data["series"]["completed_count"]/account_data["series"]["total_count"]))*100,
            (float(account_data["series"]["onhold_count"]/account_data["series"]["total_count"]))*100,
            (float(account_data["series"]["random_count"]/account_data["series"]["total_count"]))*100,
            (float(account_data["series"]["dropped_count"]/account_data["series"]["total_count"]))*100,
            (float(account_data["series"]["plantowatch_count"]/account_data["series"]["total_count"]))*100]
    if account_data["anime"]["nb_ep_watched"] == 0:
        account_data["anime"]["element_percentage"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    else:
        account_data["anime"]["element_percentage"] = [
            (float(account_data["anime"]["watching_count"]/account_data["anime"]["total_count"]))*100,
            (float(account_data["anime"]["completed_count"]/account_data["anime"]["total_count"]))*100,
            (float(account_data["anime"]["onhold_count"]/account_data["anime"]["total_count"]))*100,
            (float(account_data["anime"]["random_count"]/account_data["anime"]["total_count"]))*100,
            (float(account_data["anime"]["dropped_count"]/account_data["anime"]["total_count"]))*100,
            (float(account_data["anime"]["plantowatch_count"]/account_data["anime"]["total_count"]))*100]
    if account_data["movies"]["total_count"] == 0:
        account_data["movies"]["element_percentage"] = [0.0, 0.0, 0.0]
    else:
        account_data["movies"]["element_percentage"] = [
            (float(account_data["movies"]["completed_count"]/account_data["movies"]["total_count"]))*100,
            (float(account_data["movies"]["completed_animation_count"]/account_data["movies"]["total_count"]))*100,
            (float(account_data["movies"]["plantowatch_count"]/account_data["movies"]["total_count"]))*100]

    # Grades and levels for each media
    series_level = get_level_and_grade(user.time_spent_series)
    account_data["series_level"]       = series_level["level"]
    account_data["series_percent"]     = series_level["level_percent"]
    account_data["series_grade_id"]    = series_level["grade_id"]
    account_data["series_grade_title"] = series_level["grade_title"]

    anime_level = get_level_and_grade(user.time_spent_anime)
    account_data["anime_level"]       = anime_level["level"]
    account_data["anime_percent"]     = anime_level["level_percent"]
    account_data["anime_grade_id"]    = anime_level["grade_id"]
    account_data["anime_grade_title"] = anime_level["grade_title"]

    movies_level = get_level_and_grade(user.time_spent_movies)
    account_data["movies_level"]       = movies_level["level"]
    account_data["movies_percent"]     = movies_level["level_percent"]
    account_data["movies_grade_id"]    = movies_level["grade_id"]
    account_data["movies_grade_title"] = movies_level["grade_title"]

    knowledge_level = int(series_level["level"] + anime_level["level"] + movies_level["level"])
    knowledge_grade = get_knowledge_grade(knowledge_level)
    account_data["knowledge_level"]       = knowledge_level
    account_data["knowledge_grade_id"]    = knowledge_grade["grade_id"]
    account_data["knowledge_grade_title"] = knowledge_grade["grade_title"]

    return account_data


def get_list_count(user_id, list_type):
    if list_type is ListType.SERIES:
        media_count = db.session.query(SeriesList, func.count(SeriesList.status))\
            .filter_by(user_id=user_id).group_by(SeriesList.status).all()
    if list_type is ListType.ANIME:
        media_count = db.session.query(AnimeList, func.count(AnimeList.status))\
        .filter_by(user_id=user_id).group_by(AnimeList.status).all()
    if list_type is ListType.MOVIES:
        media_count = db.session.query(MoviesList, func.count(MoviesList.status))\
        .filter_by(user_id=user_id).group_by(MoviesList.status).all()

    watching, completed, completed_animation, onhold, \
    random, dropped, plantowatch = [0 for _ in range(7)]
    for media in media_count:
        if media[0].status == Status.WATCHING:
            watching = media[1]
        if media[0].status == Status.COMPLETED:
            completed = media[1]
        if media[0].status == Status.COMPLETED_ANIMATION:
            completed_animation = media[1]
        if media[0].status == Status.ON_HOLD:
            onhold = media[1]
        if media[0].status == Status.RANDOM:
            random = media[1]
        if media[0].status == Status.DROPPED:
            dropped = media[1]
        if media[0].status == Status.PLAN_TO_WATCH:
            plantowatch = media[1]
    total = sum(tot[1] for tot in media_count)

    return {"watching": watching,
            "completed": completed,
            "completed_animation": completed_animation,
            "onhold": onhold,
            "random": random,
            "dropped": dropped,
            "plantowatch": plantowatch,
            "total": total - plantowatch}


def get_level_and_grade(total_time_min):
    # Compute the corresponding level using the quadratic equation
    element_level_tmp = "{:.2f}".format(round((((400+80*(total_time_min))**(1/2))-20)/40, 2))
    element_level = element_level_tmp.split('.')
    element_level[0] = int(element_level[0])

    # Level and grade calculation
    list_all_levels_ranks = []
    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\\csv_data\\levels_ranks.csv")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/csv_data/levels_ranks.csv")
    with open(path, 'r') as fp:
        for line in fp:
            list_all_levels_ranks.append(line.split(";"))

    list_all_levels_ranks.pop(0)

    user_level_rank = []
    # Check if the user has a level greater than 125
    if element_level[0] > 125:
        user_level_rank.append(["General_Grade_4", "General Grade 4"])
    else:
        for rank in list_all_levels_ranks:
            if int(rank[0]) == element_level[0]:
                user_level_rank.append([str(rank[2]), str(rank[3])])

    return {"level": element_level[0],
            "level_percent": element_level[1],
            "grade_id": user_level_rank[0][0],
            "grade_title": user_level_rank[0][1]}


def get_knowledge_grade(knowledge_level):
    # Recover knowledge ranks
    list_all_knowledge_ranks = []
    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\\csv_data\\knowledge_ranks.csv")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/csv_data/knowledge_ranks.csv")
    with open(path, 'r') as fp:
        for line in fp:
            list_all_knowledge_ranks.append(line.split(";"))

    user_knowledge_rank = []
    # Check if the user has a level greater than 345
    if int(knowledge_level) > 345:
        user_knowledge_rank.append(["Knowledge_Emperor_Grade_4", "Knowledge Emperor Grade 4"])
    else:
        for rank in list_all_knowledge_ranks:
            if str(rank[0]) == str(knowledge_level):
                user_knowledge_rank.append([str(rank[1]), str(rank[2])])

    return {"grade_id": user_knowledge_rank[0][0], "grade_title": user_knowledge_rank[0][1]}


def get_badges(user_id):
    user = User.query.filter_by(id=user_id).first()

    def get_queries():
        series_data = db.session.query(Series, SeriesList, func.group_concat(SeriesGenre.genre.distinct()),
                                        func.group_concat(SeriesEpisodesPerSeason.season.distinct()),
                                        func.group_concat(SeriesEpisodesPerSeason.episodes))\
            .join(SeriesList, SeriesList.series_id == Series.id)\
            .join(SeriesGenre, SeriesGenre.series_id == Series.id)\
            .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id == Series.id)\
            .filter(SeriesList.user_id == user_id)\
            .filter(or_(SeriesGenre.genre == "Animation", SeriesGenre.genre == "Comedy", SeriesGenre.genre == "Crime",
                        SeriesGenre.genre == "Documentary", SeriesGenre.genre == "Mystery",
                        SeriesGenre.genre == "Historical", SeriesGenre.genre == "War & Politics",
                        SeriesGenre.genre == "Sci-Fi & Fantasy"))\
            .group_by(Series.id).all()

        anime_data = db.session.query(Anime, AnimeList, func.group_concat(AnimeGenre.genre.distinct()),
                                        func.group_concat(AnimeEpisodesPerSeason.season.distinct()),
                                        func.group_concat(AnimeEpisodesPerSeason.episodes))\
            .join(AnimeList, AnimeList.anime_id == Anime.id)\
            .join(AnimeGenre, AnimeGenre.anime_id == Anime.id)\
            .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == Anime.id)\
            .filter(AnimeList.user_id == user_id) \
            .filter(or_(AnimeGenre.genre == "Comedy", AnimeGenre.genre == "Police", AnimeGenre.genre == "Supernatural",
                        AnimeGenre.genre == "Music", AnimeGenre.genre == "Mystery", AnimeGenre.genre == "Historical",
                        AnimeGenre.genre == "Romance", AnimeGenre.genre == "Sci-Fi", AnimeGenre.genre == "Fantasy",
                        AnimeGenre.genre == "Horror", AnimeGenre.genre == "Thriller", AnimeGenre.genre == "Sports",
                        AnimeGenre.genre == "Slice of Life", AnimeGenre.genre == "School")) \
            .group_by(Anime.id).all()

        movies_data = db.session.query(Movies, MoviesList, func.group_concat(MoviesGenre.genre.distinct()))\
            .join(MoviesList, MoviesList.movies_id == Movies.id)\
            .join(MoviesGenre, MoviesGenre.movies_id == Movies.id)\
            .filter(MoviesList.user_id == user_id) \
            .filter(or_(MoviesGenre.genre == "Comedy", MoviesGenre.genre == "Crime", MoviesGenre.genre == "Music",
                        MoviesGenre.genre == "Mystery", MoviesGenre.genre == "History",
                        MoviesGenre.genre == "Documentary", MoviesGenre.genre == "Romance",
                        MoviesGenre.genre == "Horror", MoviesGenre.genre == "War", MoviesGenre.genre == "Fantasy",
                        MoviesGenre.genre == "Thriller", MoviesGenre.genre == "Animation",
                        MoviesGenre.genre == "Science Fiction"))\
            .group_by(Movies.id).all()

        total_data = series_data + anime_data + movies_data

        return total_data

    def get_episodes_and_time(element):
        if element[1].status == Status.COMPLETED or element[1].status == Status.COMPLETED_ANIMATION:
            try:
                return [1, element[0].runtime]
            except:
                return [element[0].total_episodes, int(element[0].episode_duration) * element[0].total_episodes]
        elif element[1].status != Status.PLAN_TO_WATCH and element[1].status != Status.RANDOM:
            nb_season = len(element[3].split(","))
            nb_episodes = element[4].split(",")[:nb_season]

            ep_duration = int(element[0].episode_duration)
            ep_counter = 0
            for i in range(0, element[1].current_season - 1):
                ep_counter += int(nb_episodes[i])
            episodes_watched = ep_counter + element[1].last_episode_watched
            time_watched = (ep_duration * episodes_watched)
            return [episodes_watched, time_watched]
        else:
            return [0, 0]

    def create_badge_dict(badge, unlocked, time=None, count=None):
        if time is not None:
            value = int(time/60)
        else:
            value = count

        badge_data = {}
        badge_data["type"] = badge.type
        badge_data["image_id"] = badge.image_id
        badge_data["title"] = badge.title
        badge_data["unlocked"] = unlocked
        badge_data["value"] = value

        return badge_data

    total_data = get_queries()
    time_spent = int(user.time_spent_anime) + int(user.time_spent_series) + int(user.time_spent_movies)

    all_badges = []
    time_by_genre = {}
    time_classic = 0
    count_completed = 0
    long_media_shows = 0
    long_media_movies = 0
    for element in total_data:
        eps_and_time = get_episodes_and_time(element)
        episodes_watched = eps_and_time[0]
        time_watched = eps_and_time[1]

        # Genres badges
        genres = element[2].split(',')
        for genre in genres:
            if genre not in time_by_genre:
                if genre == "Supernatural":
                    if "Mystery" not in time_by_genre:
                        time_by_genre["Mystery"] = time_watched
                    else:
                        time_by_genre["Mystery"] += time_watched
                elif genre == "Police":
                    if "Crime" not in time_by_genre:
                        time_by_genre["Crime"] = time_watched
                    else:
                        time_by_genre["Crime"] += time_watched
                elif genre == "War" or genre == "War & Politics" or genre == "History":
                    if "Historical" not in time_by_genre:
                        time_by_genre["Historical"] = time_watched
                    else:
                        time_by_genre["Historical"] += time_watched
                elif genre == "Sci-Fi & Fantasy":
                    if "Fantasy" not in time_by_genre:
                        time_by_genre["Fantasy"] = time_watched
                    else:
                        time_by_genre["Fantasy"] += time_watched
                    if "Science Fiction" not in time_by_genre:
                        time_by_genre["Science Fiction"] = time_watched
                    else:
                        time_by_genre["Science Fiction"] += time_watched
                elif genre == "Sci-Fi":
                    if "Science Fiction" not in time_by_genre:
                        time_by_genre["Science Fiction"] = time_watched
                    else:
                        time_by_genre["Science Fiction"] += time_watched
                elif genre == "School":
                    if "Slice of Life" not in time_by_genre:
                        time_by_genre["Slice of Life"] = time_watched
                    else:
                        time_by_genre["Slice of Life"] += time_watched
                else:
                    time_by_genre[genre] = time_watched
            else:
                time_by_genre[genre] += time_watched

        # Classic media bagdes, before 1990 without movies
        try:
            first_year = int(element[0].first_air_date.split('-')[0])
            if first_year <= 1990 and element[1].status != Status.PLAN_TO_WATCH \
                    and element[1].status != Status.RANDOM:
                time_classic += time_watched
        except:
            pass
        # Classic media bagdes, before 1990 movies
        try:
            release_date = int(element[0].release_date.split('-')[0])
            if release_date <= 1990 and element[1].status != Status.PLAN_TO_WATCH:
                time_classic += time_watched
        except:
            pass

        # Completed media badges without movies
        try:
            status = element[0].status
            if (status=="Ended" or status=="Canceled" or status=="Released") \
                    and (element[1].status == Status.COMPLETED or element[1].status == Status.COMPLETED_ANIMATION):
                count_completed += 1
        except:
            pass
        # Completed media badges movies
        try:
            status = element[0].released
            if (status=="Released") and (element[1].status == Status.COMPLETED
                                         or element[1].status == Status.COMPLETED_ANIMATION):
                count_completed += 1
        except:
            pass

        # Long media shows, more than 100 episodes
        try:
            if int(episodes_watched) >= 100:
                long_media_shows += 1
        except:
            pass

        # Long media movies, more than 2h30
        try:
            if element[0].runtime >= 150:
                long_media_movies += 1
        except:
            pass

    # Genres badges
    genres_values = ["Mystery", "Historical", "Horror", "Music", "Romance", "Sports", "Slice of Life", "Comedy",
                     "Crime", "Documentary", "Science Fiction", "Animation", "Fantasy", "Thriller"]
    for i in range(0, len(genres_values)):
        badge = db.session.query(Badges).filter_by(title=genres_values[i]).first()
        try:
            genre_time_data = time_by_genre[genres_values[i]]
        except:
            genre_time_data = 0
        count_unlocked = int((genre_time_data/60)/badge.threshold)
        badge_data = create_badge_dict(badge, count_unlocked, time=genre_time_data)
        all_badges.append(badge_data)

    # Classic badges
    badge = db.session.query(Badges).filter_by(type="classic").first()
    count_unlocked = int((time_classic/60)/badge.threshold)
    badge_data = create_badge_dict(badge, count_unlocked, time=time_classic)
    all_badges.append(badge_data)

    # Completed badges
    badge = db.session.query(Badges).filter_by(type="completed").first()
    count_unlocked = int(count_completed/badge.threshold)
    badge_data = create_badge_dict(badge, count_unlocked, count=count_completed)
    all_badges.append(badge_data)

    # Time badges
    badge = db.session.query(Badges).filter_by(type="total-time").first()
    count_unlocked = int((time_spent/1440)/badge.threshold)
    badge_data = create_badge_dict(badge, count_unlocked, time=(time_spent/24))
    all_badges.append(badge_data)

    # Long shows badges
    badge = db.session.query(Badges).filter_by(type="longshows").first()
    count_unlocked = int(long_media_shows/badge.threshold)
    badge_data = create_badge_dict(badge, count_unlocked, count=long_media_shows)
    all_badges.append(badge_data)

    # Long movies badges
    badge = db.session.query(Badges).filter_by(type="longmovies").first()
    count_unlocked = int(long_media_movies/badge.threshold)
    badge_data = create_badge_dict(badge, count_unlocked, count=long_media_movies)
    all_badges.append(badge_data)

    all_badges.sort(key=lambda x: (x['unlocked'], x['value']), reverse=True)
    total_unlocked = 0
    for item in all_badges:
        total_unlocked += item["unlocked"]

    return [all_badges, total_unlocked]


def get_all_media_data(element_data, list_type, covers_path, user_id):
    if user_id != current_user.id:
        if list_type == ListType.ANIME:
            tmp_current_list = AnimeList.query.filter_by(user_id=current_user.id).all()
        elif list_type == ListType.SERIES:
            tmp_current_list = SeriesList.query.filter_by(user_id=current_user.id).all()
        elif list_type == ListType.MOVIES:
            tmp_current_list = MoviesList.query.filter_by(user_id=current_user.id).all()

        current_list = []
        for i in range(0, len(tmp_current_list)):
            if list_type == ListType.ANIME:
                current_list.append(tmp_current_list[i].anime_id)
            elif list_type == ListType.SERIES:
                current_list.append(tmp_current_list[i].series_id)
            elif list_type == ListType.MOVIES:
                current_list.append(tmp_current_list[i].movies_id)
    else:
        current_list = []

    if list_type != ListType.MOVIES:
        watching_list    = []
        completed_list   = []
        onhold_list      = []
        random_list      = []
        dropped_list     = []
        plantowatch_list = []

        common_elements = 0
        for element in element_data:
            # Get episodes per season
            nb_season = len(element[4].split(","))
            eps_per_season = element[6].split(",")[:nb_season]
            # change str to int
            eps_per_season = [int(i) for i in eps_per_season]

            # Change first air time format
            try:
                tmp_date = datetime.strptime(element[0].first_air_date, '%Y-%m-%d')
                first_air_date = tmp_date.strftime("%d %b %Y")
            except:
                first_air_date = "Unknown"

            # Change last air time format
            try:
                tmp_date = datetime.strptime(element[0].last_air_date, '%Y-%m-%d')
                last_air_date = tmp_date.strftime("%d %b %Y")
            except:
                last_air_date = "Unknown"

            # Get actors
            try:
                tmp = element[5]
                actors = tmp.replace(',', ', ')
            except:
                actors = "Unknown"

            # Get genres
            try:
                tmp = element[2]
                genres = tmp.replace(',', ', ')
            except:
                genres = "Unknown"

            # Get networks
            try:
                tmp = element[3]
                networks = tmp.replace(',', ', ')
            except:
                networks = "Unknown"

            element_info = {"id": element[0].id,
                            "cover": "{}{}".format(covers_path, element[0].image_cover),
                            "name": element[0].name,
                            "original_name": element[0].original_name,
                            "first_air_date": first_air_date,
                            "last_air_date": last_air_date,
                            "created_by": element[0].created_by,
                            "episode_duration": element[0].episode_duration,
                            "homepage": element[0].homepage,
                            "in_production": element[0].in_production,
                            "origin_country": element[0].origin_country,
                            "total_seasons": element[0].total_seasons,
                            "total_episodes": element[0].total_episodes,
                            "status": element[0].status,
                            "vote_average": element[0].vote_average,
                            "vote_count": element[0].vote_count,
                            "synopsis": element[0].synopsis,
                            "popularity": element[0].popularity,
                            "last_episode_watched": element[1].last_episode_watched,
                            "eps_per_season": eps_per_season,
                            "current_season": element[1].current_season,
                            "score": element[1].score,
                            "actors": actors,
                            "genres": genres,
                            "networks": networks}

            if element[1].status == Status.WATCHING:
                if element[0].id in current_list:
                    watching_list.append([element_info, True])
                    common_elements += 1
                else:
                    watching_list.append([element_info, False])
            elif element[1].status == Status.COMPLETED:
                if element[0].id in current_list:
                    completed_list.append([element_info, True])
                    common_elements += 1
                else:
                    completed_list.append([element_info, False])
            elif element[1].status == Status.ON_HOLD:
                if element[0].id in current_list:
                    onhold_list.append([element_info, True])
                    common_elements += 1
                else:
                    onhold_list.append([element_info, False])
            elif element[1].status == Status.RANDOM:
                if element[0].id in current_list:
                    random_list.append([element_info, True])
                    common_elements += 1
                else:
                    random_list.append([element_info, False])
            elif element[1].status == Status.DROPPED:
                if element[0].id in current_list:
                    dropped_list.append([element_info, True])
                    common_elements += 1
                else:
                    dropped_list.append([element_info, False])
            elif element[1].status == Status.PLAN_TO_WATCH:
                if element[0].id in current_list:
                    plantowatch_list.append([element_info, True])
                    common_elements += 1
                else:
                    plantowatch_list.append([element_info, False])

        element_all_data = [[watching_list, "WATCHING"], [completed_list, "COMPLETED"], [onhold_list, "ON HOLD"],
                            [random_list, "RANDOM"], [dropped_list, "DROPPED"], [plantowatch_list, "PLAN TO WATCH"]]

        try:
            percentage = int(common_elements/len(element_data)*100)
        except:
            percentage = 0
        all_data_media = {"all_data": element_all_data,
                          "common_elements": [common_elements, len(element_data), percentage]}

        return all_data_media
    elif list_type == ListType.MOVIES:
        completed_list           = []
        completed_list_animation = []
        plantowatch_list         = []

        common_elements = 0
        for element in element_data:
            # Change release date format
            try:
                tmp_date = datetime.strptime(element[0].release_date, '%Y-%m-%d')
                release_date = tmp_date.strftime("%d %b %Y")
            except:
                release_date = "Unknown"

            # Get actors
            try:
                tmp = element[4]
                actors = tmp.replace(',', ', ')
            except:
                actors = "Unknown"

            # Get genres
            try:
                tmp = element[2]
                genres = tmp.replace(',', ', ')
            except:
                genres = "Unknown"

            # Get production companies
            try:
                tmp = element[3]
                prod_companies = tmp.replace(',', ', ')
            except:
                prod_companies = "Unknown"

            element_info = {"id": element[0].id,
                            "cover": "{}{}".format(covers_path, element[0].image_cover),
                            "name": element[0].name,
                            "original_name": element[0].original_name,
                            "release_date": release_date,
                            "homepage": element[0].homepage,
                            "runtime": element[0].runtime,
                            "original_language": element[0].original_language,
                            "synopsis": element[0].synopsis,
                            "vote_average": element[0].vote_average,
                            "vote_count": element[0].vote_count,
                            "popularity": element[0].popularity,
                            "budget": element[0].budget,
                            "revenue": element[0].revenue,
                            "tagline": element[0].tagline,
                            "score": element[1].score,
                            "actors": actors,
                            "genres": genres,
                            "prod_companies": prod_companies}

            if element[1].status == Status.COMPLETED:
                if element[0].id in current_list:
                    completed_list.append([element_info, True])
                    common_elements += 1
                else:
                    completed_list.append([element_info, False])
            elif element[1].status == Status.COMPLETED_ANIMATION:
                if element[0].id in current_list:
                    completed_list_animation.append([element_info, True])
                    common_elements += 1
                else:
                    completed_list_animation.append([element_info, False])
            elif element[1].status == Status.PLAN_TO_WATCH:
                if element[0].id in current_list:
                    plantowatch_list.append([element_info, True])
                    common_elements += 1
                else:
                    plantowatch_list.append([element_info, False])

        element_all_data = [[completed_list, "COMPLETED"], [completed_list_animation, "COMPLETED ANIMATION"] ,
                            [plantowatch_list, "PLAN TO WATCH"]]

        try:
            percentage = int(common_elements/len(element_data)*100)
        except:
            percentage = 0
        all_data_media = {"all_data": element_all_data,
                          "common_elements": [common_elements, len(element_data), percentage]}

        return all_data_media


def compute_media_time_spent(list_type):
    user = User.query.filter_by(id=current_user.id).first()

    if list_type == ListType.ANIME:
        element_data = db.session.query(AnimeList, Anime, func.group_concat(AnimeEpisodesPerSeason.episodes))\
            .join(Anime, Anime.id == AnimeList.anime_id)\
            .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == AnimeList.anime_id)\
            .filter(AnimeList.user_id == current_user.id).group_by(AnimeList.anime_id)
    elif list_type == ListType.SERIES:
        element_data = db.session.query(SeriesList, Series, func.group_concat(SeriesEpisodesPerSeason.episodes))\
            .join(Series, Series.id == SeriesList.series_id)\
            .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id == SeriesList.series_id)\
            .filter(SeriesList.user_id == current_user.id).group_by(SeriesList.series_id)
    elif list_type == ListType.MOVIES:
        element_data = db.session.query(MoviesList, Movies).join(Movies, Movies.id == MoviesList.movies_id)\
            .filter(MoviesList.user_id == current_user.id).group_by(MoviesList.movies_id)

    if list_type == ListType.ANIME or list_type == ListType.SERIES:
        total_time = 0
        for element in element_data:
            if element[0].status == Status.COMPLETED:
                try:
                    total_time += element[1].episode_duration * element[1].total_episodes
                except:
                    pass
            elif element[0].status != Status.PLAN_TO_WATCH:
                try:
                    episodes = element[2].split(",")
                    episodes = [int(x) for x in episodes]
                    for i in range(1, element[0].current_season):
                        total_time += element[1].episode_duration * episodes[i - 1]
                    total_time += element[0].last_episode_watched * element[1].episode_duration
                except:
                    pass
    elif list_type == ListType.MOVIES:
        total_time = 0
        for element in element_data:
            if element[0].status == Status.COMPLETED or element[0].status == Status.COMPLETED_ANIMATION:
                try:
                    total_time += element[1].runtime
                except:
                    pass

    if list_type == ListType.ANIME:
        user.time_spent_anime = total_time
    elif list_type == ListType.SERIES:
        user.time_spent_series = total_time
    elif list_type == ListType.MOVIES:
        user.time_spent_movies = total_time

    db.session.commit()


def set_last_update(media_name, media_type, old_status=None, new_status=None, old_season=None,
                    new_season=None, old_episode=None, new_episode=None):
    user = User.query.filter_by(id=current_user.id).first()
    element = UserLastUpdate.query.filter_by(user_id=user.id).all()
    # if len(element) >= 6:
    #     oldest_id = UserLastUpdate.query.filter_by(user_id=current_user.id)\
    #         .order_by(UserLastUpdate.date.asc()).first().id
    #     UserLastUpdate.query.filter_by(id=oldest_id).delete()
    #     db.session.commit()

    update = UserLastUpdate(user_id=user.id, media_name=media_name, media_type=media_type, old_status=old_status,
                            new_status=new_status, old_season=old_season, new_season=new_season,
                            old_episode=old_episode, new_episode=new_episode, date=datetime.utcnow())
    db.session.add(update)
    db.session.commit()


def get_follows_full_last_update(user_id):
    follows_update = db.session.query(Follow, User, UserLastUpdate)\
                               .join(User, Follow.follow_id == User.id)\
                               .join(UserLastUpdate, UserLastUpdate.user_id == Follow.follow_id)\
                               .filter(Follow.user_id == user_id)\
                               .order_by(User.username, UserLastUpdate.date.desc()).all()

    tmp = ""
    follows_data = []
    for i in range(0, len(follows_update)):
        element = follows_update[i]
        if element[1].username != tmp:
            tmp = element[1].username
            follow_data = {}
            follow_data["username"] = element[1].username
            follow_data["update"] = []

        element_data = {}
        # Season or episode update
        if element[2].old_status is None and element[2].new_status is None:
            element_data["update"] = ["S{:02d}.E{:02d}".format(element[2].old_season, element[2].old_episode),
                                      "S{:02d}.E{:02d}".format(element[2].new_season, element[2].new_episode)]

        # Category update
        elif element[2].old_status is not None and element[2].new_status is not None:
            element_data["update"] = ["{}".format(element[2].old_status.value).replace("Animation", "Anime"),
                                      "{}".format(element[2].new_status.value).replace("Animation", "Anime")]

        # Media newly added
        elif element[2].old_status is None and element[2].new_status is not None:
            element_data["update"] = ["{}".format(element[2].new_status.value)]

        element_data["date"] = element[2].date.replace(tzinfo=simple_utc()).isoformat()
        element_data["media_name"] = element[2].media_name

        if element[2].media_type == ListType.SERIES:
            element_data["category"] = "series"
        elif element[2].media_type == ListType.ANIME:
            element_data["category"] = "anime"
        elif element[2].media_type == ListType.MOVIES:
            element_data["category"] = "movie"

        # TODO: TEMP FIX
        if len(follow_data["update"]) <= 5:
            follow_data["update"].append(element_data)

        try:
            if element[1].username != follows_update[i+1][1].username:
                follows_data.append(follow_data)
            else:
                pass
        except:
            follows_data.append(follow_data)

    return follows_data


def get_user_last_update(user_id):
    last_update = UserLastUpdate.query.filter_by(user_id=user_id).order_by(UserLastUpdate.date.desc()).limit(4)
    update = []
    for element in last_update:
        element_data = {}
        # Season or episode update
        if element.old_status is None and element.new_status is None:
            element_data["update"] = ["S{:02d}.E{:02d}".format(element.old_season, element.old_episode),
                                      "S{:02d}.E{:02d}".format(element.new_season, element.new_episode)]

        # Category update
        elif element.old_status is not None and element.new_status is not None:
            element_data["update"] = ["{}".format(element.old_status.value).replace("Animation", "Anime"),
                                      "{}".format(element.new_status.value).replace("Animation", "Anime")]

        # Newly added media
        elif element.old_status is None and element.new_status is not None:
            element_data["update"] = ["{}".format(element.new_status.value)]

        # Update date
        element_data["date"] = element.date.replace(tzinfo=simple_utc()).isoformat()

        element_data["media_name"] = element.media_name

        if element.media_type == ListType.SERIES:
            element_data["category"] = "series"
        elif element.media_type == ListType.ANIME:
            element_data["category"] = "anime"
        elif element.media_type == ListType.MOVIES:
            element_data["category"] = "movie"

        update.append(element_data)

    return update


def get_follows_last_update(user_id):
    follows_update = db.session.query(Follow, User, UserLastUpdate)\
                               .join(User, Follow.follow_id == User.id)\
                               .join(UserLastUpdate, UserLastUpdate.user_id == Follow.follow_id)\
                               .filter(Follow.user_id == user_id)\
                               .order_by(UserLastUpdate.date.desc()).limit(4)

    update = []
    for element in follows_update:
        element_data = {}
        # Season or episode update
        if element[2].old_status is None and element[2].new_status is None:
            element_data["update"] = ["S{:02d}.E{:02d}".format(element[2].old_season, element[2].old_episode),
                                      "S{:02d}.E{:02d}".format(element[2].new_season, element[2].new_episode)]

        # Category update
        elif element[2].old_status is not None and element[2].new_status is not None:
            element_data["update"] = ["{}".format(element[2].old_status.value).replace("Animation", "Anime"),
                                      "{}".format(element[2].new_status.value).replace("Animation", "Anime")]

        # Newly added media
        elif element[2].old_status is None and element[2].new_status is not None:
            element_data["update"] = ["{}".format(element[2].new_status.value)]

        # Update date
        element_data["date"] = element[2].date.replace(tzinfo=simple_utc()).isoformat()

        element_data["media_name"] = element[2].media_name

        if element[2].media_type == ListType.SERIES:
            element_data["category"] = "series"
        elif element[2].media_type == ListType.ANIME:
            element_data["category"] = "anime"
        elif element[2].media_type == ListType.MOVIES:
            element_data["category"] = "movie"

        element_data["username"] = element[1].username

        update.append(element_data)

    return update


def autocomplete_search_element(element_name, list_type):
    if list_type == ListType.SERIES:
        try:
            response = requests.get("https://api.themoviedb.org/3/search/tv?api_key={0}&query={1}"
                                    .format(themoviedb_api_key, element_name))
        except:
            return [{"nb_results": 0}]

        if response.status_code == 401:
            app.logger.error('[SYSTEM] Error requesting themoviedb API : invalid API key')
            return [{"nb_results": 0}]

        data = json.loads(response.text)

        try:
            if data["total_results"] == 0:
                return [{"nb_results": 0}]
        except:
            return [{"nb_results": 0}]

        # Take only the first 6 results for the autocomplete
        # If there is an anime in the 6 results, loop until the next one
        # There are 20 results per page
        tmdb_results = []
        i = 0
        while i < data["total_results"] and i < 20 and len(tmdb_results) < 6:
            # genre_ids : list
            if "genre_ids" in data["results"][i]:
                genre_ids = data["results"][i]["genre_ids"]
            else:
                genre_ids = ["Unknown"]

            # origin_country : list
            if "origin_country" in data["results"][i]:
                origin_country = data["results"][i]["origin_country"]
            else:
                origin_country = ["Unknown"]

            # original_language : string
            if "original_language" in data["results"][i]:
                original_language = data["results"][i]["original_language"]
            else:
                original_language = "Unknown"

            # To not add anime in the series table, we need to check if it's an anime and if it comes from Japan
            if (16 in genre_ids and "JP" in origin_country) or (16 in genre_ids and original_language == "ja"):
                i = i+1
                continue

            series_data = {"tmdb_id":  data["results"][i]["id"],
                           "name":  data["results"][i]["name"]}

            if data["results"][i]["poster_path"] is not None:
                series_data["poster_path"] = "{0}{1}".format("http://image.tmdb.org/t/p/w300",
                                                             data["results"][i]["poster_path"])
            else:
                series_data["poster_path"] = url_for('static', filename="covers/series_covers/default.jpg")

            if "first_air_date" in data["results"][i] and data["results"][i]["first_air_date"].split('-') != ['']:
                series_data["first_air_date"] = data["results"][i]["first_air_date"].split('-')[0]
            else:
                series_data["first_air_date"] = "Unknown"

            tmdb_results.append(series_data)
            i = i+1

        return tmdb_results
    elif list_type == ListType.ANIME:
        try:
            response = requests.get("https://api.themoviedb.org/3/search/tv?api_key={0}&query={1}"
                                    .format(themoviedb_api_key, element_name))
        except:
            return [{"nb_results": 0}]
        if response.status_code == 401:
            app.logger.error('[SYSTEM] Error requesting themoviedb API : invalid API key')
            return [{"nb_results": 0}]

        data = json.loads(response.text)
        try:
            if data["total_results"] == 0:
                return [{"nb_results": 0}]
        except:
            return [{"nb_results": 0}]

        # Take only the first 6 results for the autocomplete
        # If there is a series in the 6 results, loop until the next one
        # There are 20 results per page
        tmdb_results = []
        i = 0
        while i < data["total_results"] and i < 20 and len(tmdb_results) < 6:
            # genre_ids : list
            if "genre_ids" in data["results"][i]:
                genre_ids = data["results"][i]["genre_ids"]
            else:
                genre_ids = ["Unknown"]

            # origin_country : list
            if "origin_country" in data["results"][i]:
                origin_country = data["results"][i]["origin_country"]
            else:
                origin_country = ["Unknown"]

            # original_language : string
            if "original_language" in data["results"][i]:
                original_language = data["results"][i]["original_language"]
            else:
                original_language = "Unknown"

            # To add only anime in the anime table, we need to check if it's an anime and it comes from Japan
            if (16 in genre_ids and "JP" in origin_country) or (16 in genre_ids and original_language == "ja"):
                anime_data = {
                    "tmdb_id": data["results"][i]["id"],
                    "name": data["results"][i]["name"]
                }

                if data["results"][i]["poster_path"] is not None:
                    anime_data["poster_path"] = "{}{}"\
                        .format("http://image.tmdb.org/t/p/w300", data["results"][i]["poster_path"])
                else:
                    anime_data["poster_path"] = url_for('static', filename="covers/anime_covers/default.jpg")

                if data["results"][i]["first_air_date"].split('-') != ['']:
                    anime_data["first_air_date"] = data["results"][i]["first_air_date"].split('-')[0]
                else:
                    anime_data["first_air_date"] = "Unknown"

                tmdb_results.append(anime_data)
            i = i+1

        return tmdb_results
    elif list_type == ListType.MOVIES:
        try:
            response = requests.get("https://api.themoviedb.org/3/search/movie?api_key={0}&query={1}"
                                    .format(themoviedb_api_key, element_name))
        except:
            return [{"nb_results": 0}]

        if response.status_code == 401:
            app.logger.error('[SYSTEM] Error requesting themoviedb API : invalid API key')
            return [{"nb_results": 0}]

        data = json.loads(response.text)
        try:
            if data["total_results"] == 0:
                return [{"nb_results": 0}]
        except:
            return [{"nb_results": 0}]

        # Take only the first 6 results for the autocomplete. There are 20 results per page
        tmdb_results = []
        i = 0
        while i < data["total_results"] and i < 20 and len(tmdb_results) < 6:
            movies_data = {"tmdb_id": data["results"][i]["id"],
                           "name": data["results"][i]["title"]}

            if data["results"][i]["poster_path"] is not None:
                movies_data["poster_path"] = "{0}{1}"\
                    .format("http://image.tmdb.org/t/p/w300", data["results"][i]["poster_path"])
            else:
                movies_data["poster_path"] = url_for('static', filename="covers/movies_covers/default.jpg")

            if "release_date" in data["results"][i] != ['']:
                movies_data["first_air_date"] = data["results"][i]["release_date"].split('-')[0]
            else:
                movies_data["first_air_date"] = "Unknown"

            tmdb_results.append(movies_data)
            i = i+1

        return tmdb_results


def add_element(element_id, list_type, element_cat):
    # Check if the ID element exist in the database
    if list_type == ListType.SERIES:
        element = Series.query.filter_by(themoviedb_id=element_id).first()
    elif list_type == ListType.ANIME:
        element = Anime.query.filter_by(themoviedb_id=element_id).first()
    elif list_type == ListType.MOVIES:
        element = Movies.query.filter_by(themoviedb_id=element_id).first()

    # If the ID exist in the database, we add the element to the user's list
    if element is not None:
        # Check if the element is already in the current's user list
        if list_type == ListType.SERIES:
            if SeriesList.query.filter_by(user_id=current_user.id, series_id=element.id).first() is not None:
                return flash("This series is already in your list", "warning")
        elif list_type == ListType.ANIME:
            if AnimeList.query.filter_by(user_id=current_user.id, anime_id=element.id).first() is not None:
                return flash("This anime is already in your list", "warning")
        elif list_type == ListType.MOVIES:
            if MoviesList.query.filter_by(user_id=current_user.id, movies_id=element.id).first() is not None:
                return flash("This movie is already in your list", "warning")

        add_element_to_user(element.id, int(current_user.id), list_type, element_cat)

    # Otherwise we recover the data from an API
    else:
        element_data = get_element_data_from_api(element_id, list_type)
        element_actors = get_element_actors_from_api(element_id, list_type)

        if element_data is None:
            return flash("There was a problem while getting the info from the API."
                         " Please try again later.", "warning")

        try:
            element_cover_path = element_data["poster_path"]
        except:
            element_cover_path = None

        element_cover_id = save_api_cover(element_cover_path, list_type)

        if element_cover_id is None:
            element_cover_id = "default.jpg"
            flash("There was a problem while getting the poster from the API."
                  " Please try to refresh later.", "warning")

        element_id = add_element_in_base(element_data, element_actors, element_cover_id, list_type)
        add_element_to_user(element_id, int(current_user.id), list_type, element_cat)


def get_element_data_from_api(api_id, list_type):
    if list_type != ListType.MOVIES:
        try:
            response = requests.get("https://api.themoviedb.org/3/tv/{0}?api_key={1}"
                                    .format(api_id, themoviedb_api_key))
        except:
            return None

        if response.status_code == 401:
            app.logger.error('[SYSTEM] Error requesting themoviedb API : invalid API key')
            return None

    elif list_type == ListType.MOVIES:
        try:
            response = requests.get("https://api.themoviedb.org/3/movie/{0}?api_key={1}"
                                    .format(api_id, themoviedb_api_key))
        except:
            return None

        if response.status_code == 401:
            app.logger.error('[SYSTEM] Error requesting themoviedb API : invalid API key')
            return None

    else:
        return None

    return json.loads(response.text)


def get_element_actors_from_api(api_id, list_type):
    if list_type != ListType.MOVIES:
        try:
            response = requests.get("https://api.themoviedb.org/3/tv/{0}/credits?api_key={1}"
                                    .format(api_id, themoviedb_api_key))
        except:
            return None
        if response.status_code == 401:
            app.logger.error('[SYSTEM] Error requesting themoviedb API : invalid API key')
            return None

    elif list_type == ListType.MOVIES:
        try:
            response = requests.get("https://api.themoviedb.org/3/movie/{0}/credits?api_key={1}"
                                    .format(api_id, themoviedb_api_key))
        except:
            return None
        if response.status_code == 401:
            app.logger.error('[SYSTEM] Error requesting themoviedb API : invalid API key')
            return None

    else:
        return None

    return json.loads(response.text)


def save_api_cover(element_cover_path, list_type):
    if element_cover_path is None:
        return "default.jpg"

    element_cover_id = "{}.jpg".format(secrets.token_hex(8))

    if list_type == ListType.SERIES:
        if platform.system() == "Windows":
            local_covers_path = os.path.join(app.root_path, "static\\covers\\series_covers\\")
        else:  # Linux & macOS
            local_covers_path = os.path.join(app.root_path, "static/covers/series_covers/")
    elif list_type == ListType.ANIME:
        if platform.system() == "Windows":
            local_covers_path = os.path.join(app.root_path, "static\\covers\\anime_covers\\")
        else:  # Linux & macOS
            local_covers_path = os.path.join(app.root_path, "static/covers/anime_covers/")
    elif list_type == ListType.MOVIES:
        if platform.system() == "Windows":
            local_covers_path = os.path.join(app.root_path, "static\\covers\\movies_covers\\")
        else:  # Linux & macOS
            local_covers_path = os.path.join(app.root_path, "static/covers/movies_covers/")

    try:
        urllib.request.urlretrieve("http://image.tmdb.org/t/p/w300{}".format(element_cover_path),
                                   "{}{}".format(local_covers_path, element_cover_id))
    except:
        return None

    img = Image.open("{}{}".format(local_covers_path, element_cover_id))
    img = img.resize((300, 450), Image.ANTIALIAS)
    img.save("{0}{1}".format(local_covers_path, element_cover_id), quality=90)

    return element_cover_id


def add_element_in_base(element_data, element_actors, element_cover_id, list_type):
    if list_type == ListType.SERIES:
        element = Series.query.filter_by(themoviedb_id=element_data["id"]).first()
    elif list_type == ListType.ANIME:
        element = Anime.query.filter_by(themoviedb_id=element_data["id"]).first()
    elif list_type == ListType.MOVIES:
        element = Movies.query.filter_by(themoviedb_id=element_data["id"]).first()

    if element is not None:
        return element.id

    if list_type != ListType.MOVIES:
        try:
            name = element_data["name"]
        except:
            name = "Unknown"
        try:
            original_name = element_data["original_name"]
        except:
            original_name = "Unknown"
        try:
            first_air_date = element_data["first_air_date"]
        except:
            first_air_date = "Unknown"
        try:
            last_air_date = element_data["last_air_date"]
        except:
            last_air_date = "Unknown"
        try:
            homepage = element_data["homepage"]
        except:
            homepage = "Unknown"
        try:
            in_production = element_data["in_production"]
        except:
            in_production = "Unknown"
        try:
            total_seasons = element_data["number_of_seasons"]
        except:
            total_seasons = "Unknown"
        try:
            total_episodes = element_data["number_of_episodes"]
        except:
            total_episodes = "Unknown"
        try:
            status = element_data["status"]
        except:
            status = "Unknown"
        try:
            vote_average = element_data["vote_average"]
        except:
            vote_average = "Unknown"
        try:
            vote_count = element_data["vote_count"]
        except:
            vote_count = "Unknown"
        try:
            synopsis = element_data["overview"]
        except:
            synopsis = "Unknown"
        try:
            popularity = element_data["popularity"]
        except:
            popularity = "Unknown"

        themoviedb_id = element_data["id"]

        # Created by
        try:
            created_by = ', '.join(x['name'] for x in element_data['created_by'])
            if created_by == "":
                created_by = "Unknown"
        except:
            created_by = "Unknown"

        # Episode duration
        try:
            episode_duration = element_data["episode_run_time"][0]
            if episode_duration == "":
                episode_duration = 0
        except:
            if list_type == ListType.ANIME:
                episode_duration = 24
            else:
                episode_duration = 0

        # Origin country
        try:
            origin_country = ", ".join(element_data["origin_country"])
            if origin_country == "":
                origin_country = "Unknown"
        except:
            origin_country = "Unknown"

        # Check if a special season exist, we do not want to take it into account
        seasons_data = []
        if len(element_data["seasons"]) == 0:
            return None

        if element_data["seasons"][0]["season_number"] == 0:
            for i in range(len(element_data["seasons"])):
                try:
                    seasons_data.append(element_data["seasons"][i+1])
                except:
                    pass
        else:
            for i in range(len(element_data["seasons"])):
                try:
                    seasons_data.append(element_data["seasons"][i])
                except:
                    pass

        # Actors names
        actors_names = []
        try:
            for i in range(0, len(element_actors["cast"])):
                try:
                    actors_names.append(element_actors["cast"][i]["name"])
                    if i == 4:
                        break
                except:
                    pass
        except:
            pass

        # Genres
        genres_data = []
        genres_id = []
        try:
            for i in range(len(element_data["genres"])):
                try:
                    genres_data.append(element_data["genres"][i]["name"])
                    genres_id.append(int(element_data["genres"][i]["id"]))
                except:
                    pass
        except:
            pass

        # Network
        networks_data = []
        try:
            for i in range(len(element_data["networks"])):
                try:
                    networks_data.append(element_data["networks"][i]["name"])
                except:
                    pass
        except:
            pass

        # Add the element to the database
        if list_type == ListType.SERIES:
            element = Series(name=name,
                             original_name=original_name,
                             image_cover=element_cover_id,
                             first_air_date=first_air_date,
                             last_air_date=last_air_date,
                             homepage=homepage,
                             in_production=in_production,
                             created_by=created_by,
                             total_seasons=total_seasons,
                             total_episodes=total_episodes,
                             episode_duration=episode_duration,
                             origin_country=origin_country,
                             status=status,
                             vote_average=vote_average,
                             vote_count=vote_count,
                             synopsis=synopsis,
                             popularity=popularity,
                             themoviedb_id=themoviedb_id,
                             last_update=datetime.utcnow())
        elif list_type == ListType.ANIME:
            element = Anime(name=name,
                            original_name=original_name,
                            image_cover=element_cover_id,
                            first_air_date=first_air_date,
                            last_air_date=last_air_date,
                            homepage=homepage,
                            in_production=in_production,
                            created_by=created_by,
                            total_seasons=total_seasons,
                            total_episodes=total_episodes,
                            episode_duration=episode_duration,
                            origin_country=origin_country,
                            status=status,
                            vote_average=vote_average,
                            vote_count=vote_count,
                            synopsis=synopsis,
                            popularity=popularity,
                            themoviedb_id=themoviedb_id,
                            last_update=datetime.utcnow())

        db.session.add(element)
        db.session.commit()

        # Add Actors
        if list_type == ListType.SERIES:
            if len(actors_names) == 0:
                actors = SeriesActors(series_id=element.id,
                                      name="Unknown")
                db.session.add(actors)
            else:
                for i in range(0, len(actors_names)):
                    actors = SeriesActors(series_id=element.id,
                                        name=actors_names[i])
                    db.session.add(actors)
        elif list_type == ListType.ANIME:
            if len(actors_names) == 0:
                actors = AnimeActors(anime_id=element.id,
                                     name="Unknown")
                db.session.add(actors)
            else:
                for i in range(0, len(actors_names)):
                    actors = AnimeActors(anime_id=element.id,
                                         name=actors_names[i])
                    db.session.add(actors)

        # Add genres
        if list_type == ListType.SERIES:
            if len(genres_data) == 0:
                genre = SeriesGenre(series_id=element.id,
                                    genre="Unknown",
                                    genre_id=0)
                db.session.add(genre)
            else:
                for i in range(0, len(genres_data)):
                    genre = SeriesGenre(series_id=element.id,
                                        genre=genres_data[i],
                                        genre_id=genres_id[i])
                    db.session.add(genre)
        elif list_type == ListType.ANIME:
            try:
                response = requests.get("https://api.jikan.moe/v3/search/anime?q={0}".format(element_data["name"]))
                data_mal = json.loads(response.text)
                mal_id = data_mal["results"][0]["mal_id"]

                response = requests.get("https://api.jikan.moe/v3/anime/{}".format(mal_id))
                data_mal = json.loads(response.text)
                genres = data_mal["genres"]

                for genre in genres:
                    add_genre = AnimeGenre(anime_id=element.id,
                                           genre=genre["name"],
                                           genre_id=int(genre["mal_id"]))
                    db.session.add(add_genre)
            except:
                if len(genres_data) == 0:
                    add_genre = AnimeGenre(anime_id=element.id,
                                            genre="Unknown",
                                            genre_id=0)
                    db.session.add(add_genre)
                else:
                    for i in range(0, len(genres_data)):
                        add_genre = AnimeGenre(anime_id=element.id,
                                               genre=genres_data[i],
                                               genre_id=genres_id[i])
                        db.session.add(add_genre)

        # Add networks
        if len(networks_data) == 0:
            network = SeriesNetwork(series_id=element.id,
                                    network="Unknown")
            db.session.add(network)
        else:
            for network_data in networks_data:
                if list_type == ListType.SERIES:
                    network = SeriesNetwork(series_id=element.id,
                                            network=network_data)
                elif list_type == ListType.ANIME:
                    network = AnimeNetwork(anime_id=element.id,
                                           network=network_data)
                db.session.add(network)

        # Add number of episodes for each season
        for season_data in seasons_data:
            if list_type == ListType.SERIES:
                season = SeriesEpisodesPerSeason(series_id=element.id,
                                                 season=season_data["season_number"],
                                                 episodes=season_data["episode_count"])
            elif list_type == ListType.ANIME:
                season = AnimeEpisodesPerSeason(anime_id=element.id,
                                                season=season_data["season_number"],
                                                episodes=season_data["episode_count"])
            db.session.add(season)

        db.session.commit()
    elif list_type == ListType.MOVIES:
        try:
            name = element_data["title"]
        except:
            name = "Unknown"
        try:
            original_name = element_data["original_title"]
        except:
            original_name = "Unknown"
        try:
            release_date = element_data["release_date"]
        except:
            release_date = "Unknown"
        try:
            homepage = element_data["homepage"]
        except:
            homepage = "Unknown"
        try:
            released = element_data["status"]
        except:
            released = "Unknown"
        try:
            vote_average = element_data["vote_average"]
        except:
            vote_average = "Unknown"
        try:
            vote_count = element_data["vote_count"]
        except:
            vote_count = "Unknown"
        try:
            synopsis = element_data["overview"]
        except:
            synopsis = "Unknown"
        try:
            popularity = element_data["popularity"]
        except:
            popularity = "Unknown"
        try:
            budget = element_data["budget"]
        except:
            budget = "Unknown"
        try:
            revenue = element_data["revenue"]
        except:
            revenue = "Unknown"
        try:
            tagline = element_data["tagline"]
        except:
            tagline = "Unknown"

        themoviedb_id = element_data["id"]

        # Runtime
        try:
            runtime = element_data["runtime"]
            if runtime == None:
                runtime = 0
        except:
            runtime = 0

        # Original language
        try:
            original_language = element_data["original_language"]
            if original_language == "":
                original_language = "Unknown"
        except:
            original_language = "Unknown"

        # Actors names
        actors_name = []
        try:
            for i in range(0, len(element_actors["cast"])):
                try:
                    actors_name.append(element_actors["cast"][i]["name"])
                    if i == 4:
                        break
                except:
                    pass
        except:
            pass

        # Genres
        genres_data = []
        genres_id = []
        try:
            for i in range(0, len(element_data["genres"])):
                try:
                    genres_data.append(element_data["genres"][i]["name"])
                    genres_id.append(int(element_data["genres"][i]["id"]))
                except:
                    pass
        except:
            pass

        # Production companies
        production_companies = []
        try:
            for i in range(0, len(element_data["production_companies"])):
                try:
                    production_companies.append(element_data["production_companies"][i]["name"])
                except:
                    pass
        except:
            pass

        # Add the element to the database
        element = Movies(name=name,
                         original_name=original_name,
                         image_cover=element_cover_id,
                         release_date=release_date,
                         homepage=homepage,
                         released=released,
                         runtime=runtime,
                         original_language=original_language,
                         vote_average=vote_average,
                         vote_count=vote_count,
                         synopsis=synopsis,
                         popularity=popularity,
                         budget=budget,
                         revenue=revenue,
                         tagline=tagline,
                         themoviedb_id=themoviedb_id)

        db.session.add(element)
        db.session.commit()

        # Add Actors
        if len(actors_name) == 0:
            actors = MoviesActors(movies_id=element.id,
                                  name="Unknown")
            db.session.add(actors)
        else:
            for i in range(0, len(actors_name)):
                actors = MoviesActors(movies_id=element.id,
                                      name=actors_name[i])
                db.session.add(actors)

        # Add genres
        if len(genres_data) == 0:
            genre = MoviesGenre(movies_id=element.id,
                                genre="Unknown",
                                genre_id=0)
            db.session.add(genre)
        else:
            for i in range(0, len(genres_data)):
                genre = MoviesGenre(movies_id=element.id,
                                    genre=genres_data[i],
                                    genre_id=genres_id[i])
                db.session.add(genre)

        # Add production companies
        if len(production_companies) == 0:
            company = MoviesProd(movies_id=element.id,
                                 production_company="Unknown")
            db.session.add(company)
        else:
            for production_company in production_companies:
                company = MoviesProd(movies_id=element.id,
                                     production_company=production_company)
                db.session.add(company)

        db.session.commit()

    return element.id


def add_element_to_user(element_id, user_id, list_type, element_cat):
    if element_cat == "Watching":
        selected_cat = Status.WATCHING
    elif element_cat == "Completed":
        selected_cat = Status.COMPLETED
    elif element_cat == "On Hold":
        selected_cat = Status.ON_HOLD
    elif element_cat == "Random":
        selected_cat = Status.RANDOM
    elif element_cat == "Dropped":
        selected_cat = Status.DROPPED
    elif element_cat == "Plan to Watch":
        selected_cat = Status.PLAN_TO_WATCH

    if list_type == ListType.SERIES:
        # Set season/episode to max if the "completed" category is selected
        if selected_cat == Status.COMPLETED:
            number_season = SeriesEpisodesPerSeason.query.filter_by(series_id=element_id).count()
            number_episode = SeriesEpisodesPerSeason.query.filter_by(series_id=element_id, season=number_season)\
                .first().episodes

            user_list = SeriesList(user_id=user_id,
                                   series_id=element_id,
                                   current_season=number_season,
                                   last_episode_watched=number_episode,
                                   status=selected_cat)
        else:
            user_list = SeriesList(user_id=user_id,
                                   series_id=element_id,
                                   current_season=1,
                                   last_episode_watched=1,
                                   status=selected_cat)

        db.session.add(user_list)
        db.session.commit()
        app.logger.info('[{}] Added a series with the ID {}'.format(user_id, element_id))
        series = Series.query.filter_by(id=element_id).first()
        set_last_update(media_name=series.name, media_type=list_type, new_status=selected_cat)
    elif list_type == ListType.ANIME:
        # Set season/episode to max if the "completed" category is selected
        if selected_cat == Status.COMPLETED:
            number_season = AnimeEpisodesPerSeason.query.filter_by(anime_id=element_id).count()
            number_episode = AnimeEpisodesPerSeason.query.filter_by(anime_id=element_id,
                                                                    season=number_season)\
                .first().episodes

            user_list = AnimeList(user_id=user_id,
                                  anime_id=element_id,
                                  current_season=number_season,
                                  last_episode_watched=number_episode,
                                  status=selected_cat)
        else:
            user_list = AnimeList(user_id=user_id,
                                  anime_id=element_id,
                                  current_season=1,
                                  last_episode_watched=1,
                                  status=selected_cat)

        db.session.add(user_list)
        db.session.commit()
        app.logger.info('[{}] Added an anime with the ID {}'.format(user_id, element_id))
        anime = Anime.query.filter_by(id=element_id).first()
        set_last_update(media_name=anime.name, media_type=list_type, new_status=selected_cat)
    elif list_type == ListType.MOVIES:
        # If it contain the "Animation" genre ==> "Completed Animation"
        if selected_cat == Status.COMPLETED:
            genres = MoviesGenre.query.filter_by(movies_id=element_id).all()
            for genre in genres:
                if (genre.genre_id == 16) or (genre.genre == "Animation"):
                    selected_cat = Status.COMPLETED_ANIMATION
                    break
                else:
                    selected_cat = Status.COMPLETED

        user_list = MoviesList(user_id=user_id,
                               movies_id=element_id,
                               status=selected_cat)

        db.session.add(user_list)
        db.session.commit()
        app.logger.info('[{}] Added movie with the ID {}'.format(user_id, element_id))
        movie = Movies.query.filter_by(id=element_id).first()
        set_last_update(media_name=movie.name, media_type=list_type, new_status=selected_cat)

    compute_media_time_spent(list_type)


def refresh_element_data(api_id, list_type):
    element_data = get_element_data_from_api(api_id, list_type)

    if list_type == ListType.SERIES:
        element = Series.query.filter_by(themoviedb_id=api_id).first()
    elif list_type == ListType.ANIME:
        element = Anime.query.filter_by(themoviedb_id=api_id).first()
    elif list_type == ListType.MOVIES:
        element = Movies.query.filter_by(themoviedb_id=api_id).first()

    if (element_data is None) or (element is None):
        app.logger.info('[SYSTEM] Could not refresh the element with the TMDb ID {}'.format(api_id))
    else:
        if list_type != ListType.MOVIES:
            try:
                name = element_data["name"]
            except:
                name = "Unknown"
            try:
                original_name = element_data["original_name"]
            except:
                original_name = "Unknown"
            try:
                first_air_date = element_data["first_air_date"]
            except:
                first_air_date = "Unknown"
            try:
                last_air_date = element_data["last_air_date"]
            except:
                last_air_date = "Unknown"
            try:
                homepage = element_data["homepage"]
            except:
                homepage = "Unknown"
            try:
                in_production = element_data["in_production"]
            except:
                pass
            try:
                total_seasons = element_data["number_of_seasons"]
            except:
                total_seasons = 0
            try:
                total_episodes = element_data["number_of_episodes"]
            except:
                total_episodes = 0
            try:
                status = element_data["status"]
            except:
                status = "Unknown"
            try:
                vote_average = element_data["vote_average"]
            except:
                vote_average = 0.0
            try:
                vote_count = element_data["vote_count"]
            except:
                vote_count = 0.0
            try:
                synopsis = element_data["overview"]
            except:
                synopsis = "Unknown"
            try:
                popularity = element_data["popularity"]
            except:
                popularity = 0.0
            try:
                poster_path = element_data["poster_path"]
            except:
                poster_path = ""

            # Refresh Created by
            try:
                created_by = ', '.join(x['name'] for x in element_data['created_by'])
                if created_by == "":
                    created_by = "Unknown"
            except:
                created_by = "Unknown"

            # Refresh Episode duration
            try:
                episode_duration = element_data["episode_run_time"][0]
                if episode_duration == "":
                    episode_duration = 0
            except:
                if list_type == ListType.ANIME:
                    episode_duration = 24
                else:
                    episode_duration = 0

            # Refresh Origin country
            try:
                origin_country = ", ".join(element_data["origin_country"])
                if origin_country == "":
                    origin_country = "Unknown"
            except:
                origin_country = "Unknown"

            # Refresh if a special season exist, we do not want to take it into account
            seasons_data = []
            if len(element_data["seasons"]) == 0:
                return None

            if element_data["seasons"][0]["season_number"] == 0:
                for i in range(len(element_data["seasons"])):
                    try:
                        seasons_data.append(element_data["seasons"][i + 1])
                    except:
                        pass
            else:
                for i in range(len(element_data["seasons"])):
                    try:
                        seasons_data.append(element_data["seasons"][i])
                    except:
                        pass

            # Refresh the cover
            if list_type == ListType.SERIES:
                if platform.system() == "Windows":
                    local_covers_path = os.path.join(app.root_path, "static\\covers\\series_covers\\")
                else:  # Linux & macOS
                    local_covers_path = os.path.join(app.root_path, "static/covers/series_covers/")
            elif list_type == ListType.ANIME:
                if platform.system() == "Windows":
                    local_covers_path = os.path.join(app.root_path, "static\\covers\\anime_covers\\")
                else:  # Linux & macOS
                    local_covers_path = os.path.join(app.root_path, "static/covers/anime_covers/")

            try:
                if poster_path != "":
                    urllib.request.urlretrieve("http://image.tmdb.org/t/p/w300{0}".format(poster_path),
                                               "{}{}".format(local_covers_path, element.image_cover))

                    img = Image.open(local_covers_path + element.image_cover)
                    img = img.resize((300, 450), Image.ANTIALIAS)
                    img.save(local_covers_path + element.image_cover, quality=90)
            except:
                app.logger.info("Error while refreshing the cover of ID {}".format(element.id))
                pass

            # Refresh the data for Anime/Series
            element.name                = name
            element.original_name       = original_name
            element.first_air_date      = first_air_date
            element.last_air_date       = last_air_date
            element.homepage            = homepage
            element.in_production       = in_production
            element.created_by          = created_by
            element.episode_duration    = episode_duration
            element.total_seasons       = total_seasons
            element.total_episodes      = total_episodes
            element.origin_country      = origin_country
            element.status              = status
            element.vote_average        = vote_average
            element.vote_count          = vote_count
            element.synopsis            = synopsis
            element.popularity          = popularity

            # Update the number of seasons and episodes
            for season_data in seasons_data:
                if list_type == ListType.SERIES:
                    season = SeriesEpisodesPerSeason.query.filter_by(series_id=element.id,
                                                                     season=season_data["season_number"]).first()
                    if season is None:
                        season = SeriesEpisodesPerSeason(series_id=element.id,
                                                         season=season_data["season_number"],
                                                         episodes=season_data["episode_count"])
                        db.session.add(season)
                    else:
                        season.episodes = season_data["episode_count"]
                elif list_type == ListType.ANIME:
                    season = AnimeEpisodesPerSeason.query.filter_by(anime_id=element.id,
                                                                    season=season_data["season_number"]).first()
                    if season is None:
                        season = AnimeEpisodesPerSeason(anime_id=element.id,
                                                        season=season_data["season_number"],
                                                        episodes=season_data["episode_count"])
                        db.session.add(season)
                    else:
                        season.episodes = season_data["episode_count"]

            # TODO: Refresh networks, genres and actors
            element.last_update = datetime.utcnow()
            db.session.commit()
            app.logger.info("[SYSTEM] Refreshed the series/anime with the ID {}".format(element.id))
        elif list_type == ListType.MOVIES:
            try:
                release_date = element_data["release_date"]
            except:
                release_date = "Unknown"
            try:
                homepage = element_data["homepage"]
            except:
                homepage = "Unknown"
            try:
                vote_average = element_data["vote_average"]
            except:
                vote_average = 0.0
            try:
                vote_count = element_data["vote_count"]
            except:
                vote_count = 0.0
            try:
                synopsis = element_data["overview"]
            except:
                synopsis = "Unknown"
            try:
                popularity = element_data["popularity"]
            except:
                popularity = 0.0
            try:
                budget = element_data["budget"]
            except:
                budget = 0.0
            try:
                revenue = element_data["revenue"]
            except:
                revenue = 0.0
            try:
                tagline = element_data["tagline"]
            except:
                tagline = "Unknown"
            try:
                poster_path = element_data["poster_path"]
            except:
                poster_path = ""

            # Refresh runtime
            try:
                runtime = element_data["runtime"]
                if runtime == None:
                    runtime = 0
            except:
                runtime = 0

            # Refresh original language
            try:
                original_language = element_data["original_language"]
                if original_language == "":
                    original_language = "Unknown"
            except:
                original_language = "Unknown"

            # Refresh the cover
            if platform.system() == "Windows":
                local_covers_path = os.path.join(app.root_path, "static\\covers\\movies_covers\\")
            else:  # Linux & macOS
                local_covers_path = os.path.join(app.root_path, "static/covers/movies_covers/")

            try:
               if  poster_path != "":
                    urllib.request.urlretrieve("http://image.tmdb.org/t/p/w300{0}".format(poster_path),
                                               "{}{}".format(local_covers_path, element.image_cover))

                    img = Image.open(local_covers_path + element.image_cover)
                    img = img.resize((300, 450), Image.ANTIALIAS)
                    img.save(local_covers_path + element.image_cover, quality=90)
            except:
                app.logger.info("Error while refreshing the movie cover of ID {}".format(element.id))
                pass

            # Refresh the movies data
            element.release_date        = release_date
            element.homepage            = homepage
            element.runtime             = runtime
            element.original_language   = original_language
            element.vote_average        = vote_average
            element.vote_count          = vote_count
            element.synopsis            = synopsis
            element.popularity          = popularity
            element.budget              = budget
            element.revenue             = revenue
            element.tagline             = tagline

            # TODO: Refresh production companies, genres and actors
            db.session.commit()
            app.logger.info("[SYSTEM] Refreshed the movie with the ID {}".format(element.id))


def save_profile_picture(form_picture):
    random_hex = secrets.token_hex(8)
    _, f_ext = os.path.splitext(form_picture.filename)
    picture_fn = random_hex + f_ext
    picture_path = os.path.join(app.root_path, 'static/profile_pics', picture_fn)
    try:
        i = Image.open(form_picture)
    except:
        return "default.jpg"
    i = i.resize((300, 300), Image.ANTIALIAS)
    i.save(picture_path, quality=90)

    return picture_fn


def add_follow(follow_username):
    follow_to_add = User.query.filter_by(username=follow_username).first()

    if (follow_to_add is None) or (follow_to_add.id == 1):
        app.logger.info('[{}] Attempt to follow user {}'.format(current_user.id, follow_username))
        return flash('This user does not exist', 'warning')

    if follow_to_add.username is current_user.username:
        return flash("You can't follow yourself", 'warning')

    else:
        follows = Follow.query.filter_by(user_id=current_user.id).all()

        for follow in follows:
            if follow_to_add.id == follow.follow_id:
                return flash('User already in your follow list', 'info')

        add_follow = Follow(user_id=current_user.id,
                            follow_id=follow_to_add.id)
        db.session.add(add_follow)
        db.session.commit()

        app.logger.info('[{}] is following the user with ID {}'.format(current_user.id, follow_to_add.id))
        flash("Follow successfully added.", 'success')


def send_reset_email(user):
    token = user.get_reset_token()
    msg = Message(subject='Password Reset Request',
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[user.email],
                  bcc=[app.config['MAIL_USERNAME']],
                  reply_to=app.config['MAIL_USERNAME'])

    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\\emails\\password_reset.html")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/emails/password_reset.html")

    email_template = open(path).read().replace("{1}", user.username)
    email_template = email_template.replace("{2}", url_for('reset_password_token', token=token, _external=True))
    msg.html = email_template

    try:
        mail.send(msg)
        return True
    except Exception as e:
        app.logger.error('[SYSTEM] Exception raised when sending reset email to user with the ID {} : {}'
                         .format(user.id, e))
        return False


def send_register_email(user):
    token = user.get_register_token()
    msg = Message(subject='MyLists Register Request',
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[user.email],
                  bcc=[app.config['MAIL_USERNAME']],
                  reply_to=app.config['MAIL_USERNAME'])

    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\\emails\\register.html")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/emails/register.html")

    email_template = open(path, 'r').read().replace("{1}", user.username)
    email_template = email_template.replace("{2}", url_for('register_account_token', token=token, _external=True))
    msg.html = email_template

    try:
        mail.send(msg)
        return True
    except Exception as e:
        app.logger.error('[SYSTEM] Exception raised when sending register email to user with the ID {} : {}'
                         .format(user.id, e))
        return False


def send_email_update_email(user):
    token = user.get_email_update_token()
    msg = Message(subject='MyList Email Update Request',
                  sender=app.config['MAIL_USERNAME'],
                  recipients=[user.email],
                  bcc=[app.config['MAIL_USERNAME']],
                  reply_to=app.config['MAIL_USERNAME'])

    if platform.system() == "Windows":
        path = os.path.join(app.root_path, "static\\emails\\email_update.html")
    else:  # Linux & macOS
        path = os.path.join(app.root_path, "static/emails/email_update.html")

    email_template = open(path, 'r').read().replace("{1}", user.username)
    email_template = email_template.replace("{2}", url_for('email_update_token', token=token, _external=True))
    msg.html = email_template

    try:
        mail.send(msg)
        return True
    except Exception as e:
        app.logger.error('[SYSTEM] Exception raised when sending email update email to user with the ID {} : {}'
                         .format(user.id, e))
        return False


def automatic_media_refresh():
    app.logger.info('[SYSTEM] Starting automatic refresh')

    # Recover all the data
    all_movies = Movies.query.all()
    all_series = Series.query.all()
    all_anime = Anime.query.all()

    # Create a list containing all the Movies TMDb ID
    all_movies_tmdb_id_list = []
    for i in range(0, len(all_movies)):
        all_movies_tmdb_id_list.append(all_movies[i].themoviedb_id)

    # Create a list containing all the Series TMDb ID
    all_series_tmdb_id_list = []
    for i in range(0, len(all_series)):
        all_series_tmdb_id_list.append(all_series[i].themoviedb_id)

    # Create a list containing all the Anime TMDb ID
    all_anime_tmdb_id_list = []
    for i in range(0, len(all_anime)):
        all_anime_tmdb_id_list.append(all_anime[i].themoviedb_id)

    # Recover from API all the changed Movies ID
    try:
        response = requests.get("https://api.themoviedb.org/3/movie/changes?api_key={0}"
                                .format(themoviedb_api_key))
    except Exception as e:
        app.logger.error('[SYSTEM] Error requesting themoviedb API : {}'.format(e))
        return
    if response.status_code == 401:
        app.logger.error('[SYSTEM] Error requesting themoviedb API : invalid API key')
        return

    try:
        all_id_movies_changes = json.loads(response.text)
    except:
        return

    # Recover from API all the changed series/anime ID
    try:
        response = requests.get("https://api.themoviedb.org/3/tv/changes?api_key={0}"
                                .format(themoviedb_api_key))
    except Exception as e:
        app.logger.error('[SYSTEM] Error requesting themoviedb API : {}'.format(e))
        return
    if response.status_code == 401:
        app.logger.error('[SYSTEM] Error requesting themoviedb API : invalid API key')
        return

    try:
        all_id_TV_changes = json.loads(response.text)
    except:
        return

    # Funtion to refresh movies
    for element in all_id_movies_changes["results"]:
        if element["id"] in all_movies_tmdb_id_list:
            refresh_element_data(element["id"], ListType.MOVIES)

    # Funtion to refresh series
    for element in all_id_TV_changes["results"]:
        if element["id"] in all_series_tmdb_id_list:
            refresh_element_data(element["id"], ListType.SERIES)

    # Funtion to refresh anime
    for element in all_id_TV_changes["results"]:
        if element["id"] in all_anime_tmdb_id_list:
            refresh_element_data(element["id"], ListType.ANIME)

    app.logger.info('[SYSTEM] Automatic refresh completed')


def refresh_db_badges():
    list_all_badges = []
    path = os.path.join(app.root_path, 'static/csv_data/badges.csv')
    with open(path) as fp:
        for line in fp:
            list_all_badges.append(line.split(";"))

    badges = Badges.query.order_by(Badges.id).all()
    for i in range(1, len(list_all_badges)):
        try:
            genre_id = str(list_all_badges[i][4])
        except:
            genre_id = None
        badges[i-1].threshold  = int(list_all_badges[i][0])
        badges[i-1].image_id   = list_all_badges[i][1]
        badges[i-1].title      = list_all_badges[i][2]
        badges[i-1].type       = list_all_badges[i][3]
        badges[i-1].genres_id  = genre_id


############################################### Add data Retroactively #################################################


def add_badges_to_db():
    list_all_badges = []
    path = os.path.join(app.root_path, 'static/csv_data/badges.csv')
    with open(path, "r") as fp:
        for line in fp:
            list_all_badges.append(line.split(";"))

    for i in range(1, len(list_all_badges)):
        try:
            genre_id = str(list_all_badges[i][4])
        except:
            genre_id = None
        badge = Badges(threshold=int(list_all_badges[i][0]),
                       image_id=list_all_badges[i][1],
                       title=list_all_badges[i][2],
                       type=list_all_badges[i][3],
                       genres_id=genre_id)
        db.session.add(badge)


def add_actors_movies():
    all_movies = Movies.query.all()
    for i in range(0, len(all_movies)):
        tmdb_movies_id = all_movies[i].themoviedb_id
        movies_id = all_movies[i].id
        response = requests.get("https://api.themoviedb.org/3/movie/{0}/credits?api_key={1}"
                                .format(tmdb_movies_id, themoviedb_api_key))
        element_actors = json.loads(response.text)

        try:
            actors_names = []
            for j in range(0, len(element_actors["cast"])):
                try:
                    actors_names.append(element_actors["cast"][j]["name"])
                    if j == 3:
                        break
                except:
                    pass
        except:
            pass

        if len(actors_names) == 0:
            actors = MoviesActors(movies_id=movies_id,
                                  name="Unknown")
            db.session.add(actors)
        else:
            for k in range(0, len(actors_names)):
                actors = MoviesActors(movies_id=movies_id,
                                      name=actors_names[k])
                db.session.add(actors)

        db.session.commit()


def add_actors_series():
    all_series = Series.query.all()
    for i in range(0, len(all_series)):
        tmdb_series_id = all_series[i].themoviedb_id
        series_id = all_series[i].id
        response = requests.get("https://api.themoviedb.org/3/tv/{0}/credits?api_key={1}"
                                .format(tmdb_series_id, themoviedb_api_key))
        element_actors = json.loads(response.text)

        try:
            actors_names = []
            for j in range(0, len(element_actors["cast"])):
                try:
                    actors_names.append(element_actors["cast"][j]["name"])
                    if j == 3:
                        break
                except:
                    pass
        except:
            pass

        if len(actors_names) == 0:
            actors = SeriesActors(series_id=series_id,
                                  name="Unknown")
            db.session.add(actors)
        else:
            for k in range(0, len(actors_names)):
                actors = SeriesActors(series_id=series_id,
                                      name=actors_names[k])
                db.session.add(actors)

        db.session.commit()


def add_actors_anime():
    all_anime = Anime.query.all()
    for i in range(0, len(all_anime)):
        tmdb_anime_id = all_anime[i].themoviedb_id
        anime_id = all_anime[i].id
        response = requests.get("https://api.themoviedb.org/3/tv/{0}/credits?api_key={1}"
                                .format(tmdb_anime_id, themoviedb_api_key))
        element_actors = json.loads(response.text)

        try:
            actors_names = []
            for j in range(0, len(element_actors["cast"])):
                try:
                    actors_names.append(element_actors["cast"][j]["name"])
                    if j == 3:
                        break
                except:
                    pass
        except:
            pass

        if len(actors_names) == 0:
            actors = AnimeActors(anime_id=anime_id,
                                 name="Unknown")
            db.session.add(actors)
        else:
            for k in range(0, len(actors_names)):
                actors = AnimeActors(anime_id=anime_id,
                                     name=actors_names[k])
                db.session.add(actors)

        db.session.commit()


############################################# TMDb API Update Scheduler ################################################

app.apscheduler.add_job(func=automatic_media_refresh, trigger='cron', hour=3, id="{}".format(secrets.token_hex(8)))

################################################## UNUSED FUNCTIONS ####################################################

# Personal statistics
def get_statistics(user_id, list_type):
    # get the number of element per score
    user = User.query.filter_by(id=user_id).first()
    if list_type == ListType.SERIES:
        score_0 = SeriesList.query.filter_by(user_id=user_id).filter(SeriesList.score >= 0, SeriesList.score < 1).all()
        score_1 = SeriesList.query.filter_by(user_id=user_id).filter(SeriesList.score >= 1, SeriesList.score < 2).all()
        score_2 = SeriesList.query.filter_by(user_id=user_id).filter(SeriesList.score >= 2, SeriesList.score < 3).all()
        score_3 = SeriesList.query.filter_by(user_id=user_id).filter(SeriesList.score >= 3, SeriesList.score < 4).all()
        score_4 = SeriesList.query.filter_by(user_id=user_id).filter(SeriesList.score >= 4, SeriesList.score < 5).all()
        score_5 = SeriesList.query.filter_by(user_id=user_id).filter(SeriesList.score >= 5, SeriesList.score < 6).all()
        score_6 = SeriesList.query.filter_by(user_id=user_id).filter(SeriesList.score >= 6, SeriesList.score < 7).all()
        score_7 = SeriesList.query.filter_by(user_id=user_id).filter(SeriesList.score >= 7, SeriesList.score < 8).all()
        score_8 = SeriesList.query.filter_by(user_id=user_id).filter(SeriesList.score >= 8, SeriesList.score < 9).all()
        score_9 = SeriesList.query.filter_by(user_id=user_id).filter(SeriesList.score >= 9, SeriesList.score<=10).all()
    elif list_type == ListType.ANIME:
        score_0 = AnimeList.query.filter_by(user_id=user_id).filter(AnimeList.score >= 0, AnimeList.score < 1).all()
        score_1 = AnimeList.query.filter_by(user_id=user_id).filter(AnimeList.score >= 1, AnimeList.score < 2).all()
        score_2 = AnimeList.query.filter_by(user_id=user_id).filter(AnimeList.score >= 2, AnimeList.score < 3).all()
        score_3 = AnimeList.query.filter_by(user_id=user_id).filter(AnimeList.score >= 3, AnimeList.score < 4).all()
        score_4 = AnimeList.query.filter_by(user_id=user_id).filter(AnimeList.score >= 4, AnimeList.score < 5).all()
        score_5 = AnimeList.query.filter_by(user_id=user_id).filter(AnimeList.score >= 5, AnimeList.score < 6).all()
        score_6 = AnimeList.query.filter_by(user_id=user_id).filter(AnimeList.score >= 6, AnimeList.score < 7).all()
        score_7 = AnimeList.query.filter_by(user_id=user_id).filter(AnimeList.score >= 7, AnimeList.score < 8).all()
        score_8 = AnimeList.query.filter_by(user_id=user_id).filter(AnimeList.score >= 8, AnimeList.score < 9).all()
        score_9 = AnimeList.query.filter_by(user_id=user_id).filter(AnimeList.score >= 9, AnimeList.score<=10).all()

    elements_per_score = [score_0, score_1, score_2, score_3, score_4, score_5,score_6, score_7, score_8, score_9]
    element_count_per_score = []
    for i in range(0, len(elements_per_score)):
        if elements_per_score[i] is None:
            element_count_per_score.append(0)
        else:
            element_count_per_score.append(len(elements_per_score[i]))
    scores = ["0 - 1", "1 - 2", "2 - 3", "3 - 4", "4 - 5", "5 - 6", "6 - 7", "7 - 8", "8 - 9", "9 - 10"]

    # Recover the time spent watching element per score
    if list_type == ListType.ANIME:
        element_data = db.session.query(Anime, AnimeList,
                                        func.group_concat(AnimeGenre.genre.distinct()),
                                        func.group_concat(AnimeNetwork.network.distinct()),
                                        func.group_concat(AnimeEpisodesPerSeason.season.distinct()),
                                        func.group_concat(AnimeEpisodesPerSeason.episodes))\
            .join(AnimeList, AnimeList.anime_id == Anime.id)\
            .join(AnimeGenre, AnimeGenre.anime_id == Anime.id)\
            .join(AnimeNetwork, AnimeNetwork.anime_id == Anime.id)\
            .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == Anime.id)\
            .filter(AnimeList.user_id == user.id).group_by(Anime.id).order_by(Anime.name.asc()).all()
    elif list_type == ListType.SERIES:
        element_data = db.session.query(Series, SeriesList,
                                        func.group_concat(SeriesGenre.genre.distinct()),
                                        func.group_concat(SeriesNetwork.network.distinct()),
                                        func.group_concat(SeriesEpisodesPerSeason.season.distinct()),
                                        func.group_concat(SeriesEpisodesPerSeason.episodes))\
            .join(SeriesList, SeriesList.series_id == Series.id)\
            .join(SeriesGenre, SeriesGenre.series_id == Series.id)\
            .join(SeriesNetwork, SeriesNetwork.series_id == Series.id)\
            .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id == Series.id)\
            .filter(SeriesList.user_id == user.id).group_by(Series.id).order_by(Series.name.asc()).all()

    all_data = []
    for i in range(0, len(elements_per_score)):
        episodes_count_per_score = 0
        element_time_per_score = 0
        for j in range(0, len(elements_per_score[i])):
            if list_type == ListType.ANIME:
                element_id = elements_per_score[i][j].anime_id
            elif list_type == ListType.SERIES:
                element_id = elements_per_score[i][j].series_id

            element_time = 0
            for element in element_data:
                if element_id == element[0].id:
                    ep_duration = element[0].episode_duration

                    nb_season = len(element[4].split(","))
                    nb_episodes = element[5].split(",")[:nb_season]

                    ep_counter = 0
                    for k in range(0, element[1].current_season - 1):
                       ep_counter += int(nb_episodes[k])
                    episodes_count = ep_counter + element[1].last_episode_watched
                    element_time += ep_duration * episodes_count

            episodes_count_per_score += episodes_count
            element_time_per_score += element_time

        data_by_score = {"episodes_watched": episodes_count_per_score,
                         "time_watched": int(element_time_per_score/60)}

        all_data.append(data_by_score)

    time_total_chart = []
    for data in all_data:
       time_total_chart.append(data["time_watched"])

    episodes_total_chart = []
    for data in all_data:
       episodes_total_chart.append(data["episodes_watched"])

    return [scores, element_count_per_score, time_total_chart, episodes_total_chart]

# Old achievements function
def get_achievements(user_id, list_type):
    if list_type == ListType.ANIME:
        element_data = db.session.query(Anime, AnimeList,
                                        func.group_concat(AnimeGenre.genre_id.distinct()),
                                        func.group_concat(AnimeEpisodesPerSeason.season.distinct()),
                                        func.group_concat(AnimeEpisodesPerSeason.episodes))\
            .join(AnimeList, AnimeList.anime_id == Anime.id)\
            .join(AnimeGenre, AnimeGenre.anime_id == Anime.id)\
            .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == Anime.id)\
            .filter(AnimeList.user_id == user_id).group_by(Anime.id).order_by(Anime.name.asc()).all()
        genre_id = ['13', '18', '19', '7', '22', '36', '29', '30', '40', '14', '9']
        media = "A"
    elif list_type == ListType.SERIES:
        element_data = db.session.query(Series, SeriesList,
                                        func.group_concat(SeriesGenre.genre_id.distinct()),
                                        func.group_concat(SeriesEpisodesPerSeason.season.distinct()),
                                        func.group_concat(SeriesEpisodesPerSeason.episodes))\
            .join(SeriesList, SeriesList.series_id == Series.id)\
            .join(SeriesGenre, SeriesGenre.series_id == Series.id)\
            .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id == Series.id)\
            .filter(SeriesList.user_id == user_id).group_by(Series.id).order_by(Series.name.asc()).all()
        genre_id = ['9648', '10759', '35', '80', '99', '18', '10765']
        media = "S"
    elif list_type == ListType.MOVIES:
        element_data = db.session.query(Movies, MoviesList,
                                        func.group_concat(MoviesGenre.genre_id.distinct()))\
            .join(MoviesList, MoviesList.movies_id == Movies.id)\
            .join(MoviesGenre, MoviesGenre.movies_id == Movies.id)\
            .filter(MoviesList.user_id == user_id).group_by(Movies.id).order_by(Movies.name.asc()).all()
        genre_id = ['16', '35', '99', '14', '36', '27', '10402', '9648', '10749', '878', '53']
        media = "M"
    user = User.query.filter_by(id=user_id).first()

    def get_episodes_and_time(element):
        # Get episodes per season
        nb_season = len(element[3].split(","))
        nb_episodes = element[4].split(",")[:nb_season]

        ep_duration = int(element[0].episode_duration)
        ep_counter = 0
        for i in range(0, element[1].current_season - 1):
            ep_counter += int(nb_episodes[i])
        episodes_watched = ep_counter + element[1].last_episode_watched
        time_watched = ep_duration * episodes_watched

        return [episodes_watched, time_watched]

    element_count_1, element_count_2, element_count_3, element_count_4, element_count_5, element_count_6, \
    element_count_7, element_count_8, element_count_9, element_count_10, element_count_11 = [0 for _ in range(11)]
    element_time_1, element_time_2, element_time_3, element_time_4, element_time_5, element_time_6, element_time_7, \
    element_time_8, element_time_9, element_time_10, element_time_11 = [0 for _ in range(11)]
    element_episodes_1, element_episodes_2, element_episodes_3, element_episodes_4, element_episodes_5, \
    element_episodes_6, element_episodes_7, element_episodes_8, element_episodes_9, element_episodes_10, \
    element_episodes_11 = [0 for _ in range(11)]
    element_name_1, element_name_2, element_name_3, element_name_4, element_name_5, element_name_6, element_name_7, \
    element_name_8, element_name_9, element_name_10, element_name_11 = [[] for _ in range(11)]
    element_time_classic = 0
    element_count_classic = 0
    element_episodes_classic = 0
    element_count_finished = 0
    element_count_long = 0
    element_count_old = 0
    unlocked_badges = 0
    unlocked_levels = 0
    all_badges = []
    all_air_date_years = []
    element_name_old = []
    element_name_long = []
    element_name_classic = []
    for element in element_data:
        if element[1].status != Status.PLAN_TO_WATCH and element[1].status != Status.RANDOM:
            # Get the genre in a list
            genres = element[2].split(',')

            if list_type == ListType.ANIME:
                try:
                    if '13' in genres:
                        element_count_1 += 1
                        element_episodes_1 += get_episodes_and_time(element)[0]
                        element_time_1 += get_episodes_and_time(element)[1]
                        element_name_1.append(element[0].name)
                    if '18' in genres:
                        element_count_2 += 1
                        element_episodes_2 += get_episodes_and_time(element)[0]
                        element_time_2 += get_episodes_and_time(element)[1]
                        element_name_2.append(element[0].name)
                    if '19' in genres:
                        element_count_3 += 1
                        element_episodes_3 += get_episodes_and_time(element)[0]
                        element_time_3 += get_episodes_and_time(element)[1]
                        element_name_3.append(element[0].name)
                    if '7' in genres:
                        element_count_4 += 1
                        element_episodes_4 += get_episodes_and_time(element)[0]
                        element_time_4 += get_episodes_and_time(element)[1]
                        element_name_4.append(element[0].name)
                    if '22' in genres:
                        element_count_5 += 1
                        element_episodes_5 += get_episodes_and_time(element)[0]
                        element_time_5 += get_episodes_and_time(element)[1]
                        element_name_5.append(element[0].name)
                    if '36' in genres:
                        element_count_6 += 1
                        element_episodes_6 += get_episodes_and_time(element)[0]
                        element_time_6 += get_episodes_and_time(element)[1]
                        element_name_6.append(element[0].name)
                    if '29' in genres:
                        element_count_7 += 1
                        element_episodes_7 += get_episodes_and_time(element)[0]
                        element_time_7 += get_episodes_and_time(element)[1]
                        element_name_7.append(element[0].name)
                    if '30' in genres:
                        element_count_8 += 1
                        element_episodes_8 += get_episodes_and_time(element)[0]
                        element_time_8 += get_episodes_and_time(element)[1]
                        element_name_8.append(element[0].name)
                    if '40' in genres:
                        element_count_9 += 1
                        element_episodes_9 += get_episodes_and_time(element)[0]
                        element_time_9 += get_episodes_and_time(element)[1]
                        element_name_9.append(element[0].name)
                    if '14' in genres:
                        element_count_10 += 1
                        element_episodes_10 += get_episodes_and_time(element)[0]
                        element_time_10 += get_episodes_and_time(element)[1]
                        element_name_10.append(element[0].name)
                    if '9' in genres:
                        element_count_11 += 1
                        element_episodes_11 += get_episodes_and_time(element)[0]
                        element_time_11 += get_episodes_and_time(element)[1]
                        element_name_11.append(element[0].name)
                except:
                    pass
            elif list_type == ListType.SERIES:
                try:
                    if '9648' in genres:
                        element_count_1 += 1
                        element_episodes_1 += get_episodes_and_time(element)[0]
                        element_time_1 += get_episodes_and_time(element)[1]
                        element_name_1.append(element[0].name)
                    if '10759' in genres:
                        element_count_2 += 1
                        element_episodes_2 += get_episodes_and_time(element)[0]
                        element_time_2 += get_episodes_and_time(element)[1]
                        element_name_2.append(element[0].name)
                    if '35' in genres:
                        element_count_3 += 1
                        element_episodes_3 += get_episodes_and_time(element)[0]
                        element_time_3 += get_episodes_and_time(element)[1]
                        element_name_3.append(element[0].name)
                    if '80' in genres:
                        element_count_4 += 1
                        element_episodes_4 += get_episodes_and_time(element)[0]
                        element_time_4 += get_episodes_and_time(element)[1]
                        element_name_4.append(element[0].name)
                    if '99' in genres:
                        element_count_5 += 1
                        element_episodes_5 += get_episodes_and_time(element)[0]
                        element_time_5 += get_episodes_and_time(element)[1]
                        element_name_5.append(element[0].name)
                    if '18' in genres:
                        element_count_6 += 1
                        element_episodes_6 += get_episodes_and_time(element)[0]
                        element_time_6 += get_episodes_and_time(element)[1]
                        element_name_6.append(element[0].name)
                    if '10765' in genres:
                        element_count_7 += 1
                        element_episodes_7 += get_episodes_and_time(element)[0]
                        element_time_7 += get_episodes_and_time(element)[1]
                        element_name_7.append(element[0].name)
                except:
                    pass
            elif list_type == ListType.MOVIES:
                try:
                    if '16' in genres:
                        element_count_1 += 1
                        element_time_1 += element[0].runtime
                        element_name_1.append(element[0].name)
                    if '35' in genres:
                        element_count_2 += 1
                        element_time_2 += element[0].runtime
                        element_name_2.append(element[0].name)
                    if '99' in genres:
                        element_count_3 += 1
                        element_time_3 += element[0].runtime
                        element_name_3.append(element[0].name)
                    if '14' in genres:
                        element_count_4 += 1
                        element_time_4 += element[0].runtime
                        element_name_4.append(element[0].name)
                    if '36' in genres:
                        element_count_5 += 1
                        element_time_5 += element[0].runtime
                        element_name_5.append(element[0].name)
                    if '27' in genres:
                        element_count_6 += 1
                        element_time_6 += element[0].runtime
                        element_name_6.append(element[0].name)
                    if '10402' in genres:
                        element_count_7 += 1
                        element_time_7 += element[0].runtime
                        element_name_7.append(element[0].name)
                    if '9648' in genres:
                        element_count_8 += 1
                        element_time_8 += element[0].runtime
                        element_name_8.append(element[0].name)
                    if '10749' in genres:
                        element_count_9 += 1
                        element_time_9 += element[0].runtime
                        element_name_9.append(element[0].name)
                    if '878' in genres:
                        element_count_10 += 1
                        element_time_10 += element[0].runtime
                        element_name_10.append(element[0].name)
                    if '53' in genres:
                        element_count_11 += 1
                        element_time_11 += element[0].runtime
                        element_name_11.append(element[0].name)
                except:
                    pass

        if list_type != ListType.MOVIES:
            try:
                first_year = int(element[0].first_air_date.split('-')[0])
                if 1990 <= first_year <= 2000 and element[1].status != Status.PLAN_TO_WATCH:
                    element_count_classic += 1
                    element_episodes_classic += get_episodes_and_time(element)[0]
                    element_time_classic += get_episodes_and_time(element)[1]
                    element_name_classic.append(element[0].name)
            except:
                pass

            try:
                status = element[0].status
                if (status == "Ended" or status == "Canceled") and element[1].status == Status.COMPLETED:
                    element_count_finished += 1
            except:
                pass

            try:
                element_episodes = get_episodes_and_time(element)[0]
                if int(element_episodes) >= 100:
                    element_count_long += 1
                    element_name_long.append(element[0].name)
            except:
                pass

            try:
                year_last_air_date = element[0].last_air_date.split('-')[0]
                if (int(year_last_air_date) <= 1980) and (element[1].status == Status.COMPLETED):
                    element_count_old += 1
                    element_name_old.append(element[0].name)
                if element[1].status == Status.COMPLETED:
                    all_air_date_years.append(element[0].first_air_date.split('-')[0])
            except:
                pass
        elif list_type == ListType.MOVIES:
            try:
                release_date = int(element[0].release_date.split('-')[0])
                if 1990 <= release_date <= 2000 and element[1].status != Status.PLAN_TO_WATCH:
                    element_count_classic += 1
                    element_time_classic += element[0].runtime
                    element_name_classic.append(element[0].name)
            except:
                pass

            try:
                if element[1].status == Status.COMPLETED or element[1].status == Status.COMPLETED_ANIMATION:
                    element_count_finished += 1
                element_runtime = element[0].runtime
                if element_runtime >= 150:
                    element_count_long += 1
                    element_name_long.append(element[0].name)
            except:
                 pass

            try:
                air_date = element[0].release_date.split('-')[0]
                if (int(air_date) <= 1980) and (element[1].status == Status.COMPLETED
                                                or element[1].status == Status.COMPLETED_ANIMATION):
                    element_count_old += 1
                    element_name_old.append(element[0].name)
            except:
                pass

            try:
                if element[1].status == Status.COMPLETED or element[1].status == Status.COMPLETED_ANIMATION:
                    all_air_date_years.append(element[0].release_date.split('-')[0])
            except:
                pass

    if list_type == ListType.ANIME:
        time_spent = int(user.time_spent_anime/1440)
    elif list_type == ListType.SERIES:
        time_spent = int(user.time_spent_series/1440)
    elif list_type == ListType.MOVIES:
        time_spent = int(user.time_spent_movies/1440)

    ####################################################################################################################
    # Genres achievements
    time_list = [element_time_1, element_time_2, element_time_3, element_time_4, element_time_5, element_time_6,
                 element_time_7, element_time_8, element_time_9, element_time_10, element_time_11]
    count_list = [element_count_1, element_count_2, element_count_3, element_count_4, element_count_5, element_count_6,
                  element_count_7, element_count_8, element_count_9, element_count_10, element_count_11]
    name_list = [element_name_1, element_name_2, element_name_3, element_name_4, element_name_5, element_name_6,
                 element_name_7, element_name_8, element_name_9, element_name_10, element_name_11]
    episodes_list = [element_episodes_1, element_episodes_2, element_episodes_3, element_episodes_4, element_episodes_5,
                     element_episodes_6, element_episodes_7, element_episodes_8, element_episodes_9,
                     element_episodes_10, element_episodes_11]
    for i in range(0, len(genre_id)):
        achievements = Achievements.query.filter_by(media=media, genre=genre_id[i]).all()
        test = 0
        for achievement in achievements:
            if int(time_list[i]/60) < int(achievement.threshold):
                if achievement.level == "Level max":
                    level = "Level 3"
                else:
                    level = "{} {}".format(achievement.level.split()[0], int(achievement.level.split()[1]) - 1)
                achievement_data = {"type": achievement.type,
                                    "threshold": achievement.threshold,
                                    "image_id": achievement.image_id,
                                    "level": level,
                                    "title": achievement.title,
                                    "element_time": int(time_list[i]/60),
                                    "element_count": count_list[i],
                                    "element_name": name_list[i],
                                    "element_episodes": episodes_list[i],
                                    "element_percentage": round((int(time_list[i]/60)*100)/(achievement.threshold), 2)}
                break
            else:
                unlocked_levels += 1
                test += 1
                if test == 4:
                    unlocked_badges += 1
                    achievement_data = {
                        "type": achievement.type,
                        "threshold": achievement.threshold,
                        "image_id": achievement.image_id,
                        "level": achievement.level,
                        "title": achievement.title,
                        "element_time": int(time_list[i]/60),
                        "element_count": count_list[i],
                        "element_name": name_list[i],
                        "element_episodes": episodes_list[i],
                        "element_percentage": round((int(time_list[i]/60)*100)/(achievement.threshold),2)}
                    break

        all_badges.append(achievement_data)

    ####################################################################################################################
    # source/airing_date achievements
    achievements = Achievements.query.filter_by(media=media, type="classic").all()
    test = 0
    for achievement in achievements:
        if (element_time_classic/60) < achievement.threshold:
            if achievement.level == "Level max":
                level = "Level 3"
            else:
                level = "{} {}".format(achievement.level.split()[0], int(achievement.level.split()[1]) - 1)
            achievement_data = {
                "type": achievement.type,
                "threshold": achievement.threshold,
                "image_id": achievement.image_id,
                "level": level,
                "title": achievement.title,
                "element_time": int(element_time_classic/60),
                "element_count": element_count_classic,
                "element_name": element_name_classic,
                "element_episodes": element_episodes_classic,
                "element_percentage": round((int(element_time_classic/60)*100)/(achievement.threshold), 2)}
            break
        else:
            unlocked_levels += 1
            test += 1
            if test == 4:
                unlocked_badges += 1
                achievement_data = {
                    "type": achievement.type,
                    "threshold": achievement.threshold,
                    "image_id": achievement.image_id,
                    "level": achievement.level,
                    "title": achievement.title,
                    "element_time": int(element_time_classic/60),
                    "element_count": element_count_classic,
                    "element_name": element_name_classic,
                    "element_episodes": element_episodes_classic,
                    "element_percentage": round((int(element_time_classic/60)*100)/(achievement.threshold), 2)}
                break
    all_badges.append(achievement_data)

    ####################################################################################################################
    # Finished achievements
    achievements = Achievements.query.filter_by(media=media, type="finished").all()
    test = 0
    for achievement in achievements:
        if int(element_count_finished) < int(achievement.threshold):
            if achievement.level == "Level max":
                level = "Level 11"
            else:
                level = "{} {}".format(achievement.level.split()[0], int(achievement.level.split()[1]) - 1)
            achievement_data = {"type": achievement.type,
                                "threshold": achievement.threshold,
                                "image_id": achievement.image_id,
                                "level": level,
                                "title": achievement.title,
                                "element_count": element_count_finished,
                                "element_percentage": round((element_count_finished*100)/(achievement.threshold), 2)}
            break
        else:
            unlocked_levels += 1
            test += 1
            if test == 12:
                unlocked_badges += 1
                achievement_data = {
                    "type": achievement.type,
                    "threshold": achievement.threshold,
                    "image_id": achievement.image_id,
                    "level": achievement.level,
                    "title": achievement.title,
                    "element_count": element_count_finished,
                    "element_percentage": round((element_count_finished*100)/(achievement.threshold), 2)}
                break
    all_badges.append(achievement_data)

    ####################################################################################################################
    # Time achievements
    achievements = Achievements.query.filter_by(media=media, type="time").all()
    test = 0
    for achievement in achievements:
        if time_spent < int(achievement.threshold):
            if achievement.level == "Level max":
                level = "Level 3"
            else:
                level = "{} {}".format(achievement.level.split()[0], int(achievement.level.split()[1]) - 1)
            achievement_data = {"type": achievement.type,
                                "threshold": achievement.threshold,
                                "image_id": achievement.image_id,
                                "level": level,
                                "title": achievement.title,
                                "element_time": int(time_spent),
                                "element_percentage": round((time_spent*100)/(achievement.threshold), 2)}
            break
        else:
            unlocked_levels += 1
            test += 1
            if test == 4:
                unlocked_badges += 1
                achievement_data = {"type": achievement.type,
                                    "threshold": achievement.threshold,
                                    "image_id": achievement.image_id,
                                    "level": achievement.level,
                                    "title": achievement.title,
                                    "element_time": int(time_spent),
                                    "element_percentage": round((time_spent*100)/(achievement.threshold), 2)}
                break
    all_badges.append(achievement_data)

    ####################################################################################################################
    # Miscellaneous: Long runner
    achievement = Achievements.query.filter_by(media=media, type="long").first()
    if element_count_long < int(achievement.threshold):
        achievement_data = {"type": achievement.type,
                            "threshold": achievement.threshold,
                            "image_id": achievement.image_id,
                            "level": "Level 0",
                            "title": achievement.title,
                            "element_count": element_count_long,
                            "element_name": element_name_long,
                            "element_percentage": round((element_count_long*100)/(achievement.threshold), 2)}
    else:
        unlocked_levels += 1
        unlocked_badges += 1
        achievement_data = {"type": achievement.type,
                            "threshold": achievement.threshold,
                            "image_id": achievement.image_id,
                            "level": achievement.level,
                            "title": achievement.title,
                            "element_count": element_count_long,
                            "element_name": element_name_long,
                            "element_percentage": round((element_count_long*100)/(achievement.threshold), 2)}
    all_badges.append(achievement_data)

    # Miscellaneous: old element
    achievement = Achievements.query.filter_by(media=media, type="old").first()
    if element_count_old < int(achievement.threshold):
        achievement_data = {"type": achievement.type,
                            "threshold": achievement.threshold,
                            "image_id": achievement.image_id,
                            "level": "Level 0",
                            "title": achievement.title,
                            "element_count": element_count_old,
                            "element_name": element_name_old,
                            "element_percentage": round((element_count_old*100)/(achievement.threshold), 2)}
    else:
        unlocked_levels += 1
        unlocked_badges += 1
        achievement_data = {"type": achievement.type,
                            "threshold": achievement.threshold,
                            "image_id": achievement.image_id,
                            "level": achievement.level,
                            "title": achievement.title,
                            "element_count": element_count_old,
                            "element_name": element_name_old,
                            "element_percentage": round((element_count_old*100)/(achievement.threshold), 2)}
    all_badges.append(achievement_data)

    # Miscellaneous: Different years of first airing
    achievement = Achievements.query.filter_by(media=media, type="year").first()
    all_air_date_years = list(dict.fromkeys(all_air_date_years))
    if len(all_air_date_years) < int(achievement.threshold):
        achievement_data = {"type": achievement.type,
                            "threshold": achievement.threshold,
                            "image_id": achievement.image_id,
                            "level": "Level 0",
                            "title": achievement.title,
                            "element_count": len(all_air_date_years),
                            "element_percentage": round((len(all_air_date_years)*100)/(achievement.threshold), 2)}
    else:
        unlocked_levels += 1
        unlocked_badges += 1
        achievement_data = {"type": achievement.type,
                            "threshold": achievement.threshold,
                            "image_id": achievement.image_id,
                            "level": achievement.level,
                            "title": achievement.title,
                            "element_count": len(all_air_date_years),
                            "element_percentage": round((len(all_air_date_years)*100)/(achievement.threshold), 2)}
    all_badges.append(achievement_data)

    ####################################################################################################################
    achievements_data = {"all_badges": all_badges,
                         "unlocked_badges": unlocked_badges,
                         "unlocked_levels": unlocked_levels}

    return achievements_data
def add_achievements_to_db():
    list_all_achievements = []
    path = os.path.join(app.root_path, '')
    with open(path, "r") as fp:
        for line in fp:
            list_all_achievements.append(line.split(";"))

    for i in range(1, len(list_all_achievements)):
        try:
            genre = int(list_all_achievements[i][6])
        except:
            genre = None
        achievement = Achievements(media=list_all_achievements[i][0],
                                   threshold=int(list_all_achievements[i][1]),
                                   image_id=list_all_achievements[i][2],
                                   level=list_all_achievements[i][4],
                                   title=list_all_achievements[i][3],
                                   type=list_all_achievements[i][5],
                                   genre=genre)
        db.session.add(achievement)
def refresh_db_achievements():
    list_all_achievements = []
    path = os.path.join(app.root_path, '')
    with open(path, "r") as fp:
        for line in fp:
            list_all_achievements.append(line.split(";"))

    achievements = Achievements.query.order_by(Achievements.id).all()
    for i in range(1, len(list_all_achievements)):
        try:
            genre = int(list_all_achievements[i][6])
        except:
            genre = None
        achievements[i-1].media       = list_all_achievements[i][0]
        achievements[i-1].threshold   = int(list_all_achievements[i][1])
        achievements[i-1].image_id    = list_all_achievements[i][2]
        achievements[i-1].level       = list_all_achievements[i][4]
        achievements[i-1].title       = list_all_achievements[i][3]
        achievements[i-1].type        = list_all_achievements[i][5]
        achievements[i-1].genre       = genre

# Recover all (genre, time) by user in a dict
def get_all_genres_by_user(user_id):
    user = User.query.filter_by(id=user_id).first()

    series_data = db.session.query(Series, SeriesList, func.group_concat(SeriesGenre.genre.distinct()),
                                   func.group_concat(SeriesEpisodesPerSeason.season.distinct()),
                                   func.group_concat(SeriesEpisodesPerSeason.episodes)) \
        .join(SeriesList, SeriesList.series_id == Series.id) \
        .join(SeriesGenre, SeriesGenre.series_id == Series.id) \
        .join(SeriesEpisodesPerSeason, SeriesEpisodesPerSeason.series_id == Series.id) \
        .filter(SeriesList.user_id == user_id).group_by(Series.id).all()

    anime_data = db.session.query(Anime, AnimeList, func.group_concat(AnimeGenre.genre.distinct()),
                                  func.group_concat(AnimeEpisodesPerSeason.season.distinct()),
                                  func.group_concat(AnimeEpisodesPerSeason.episodes)) \
        .join(AnimeList, AnimeList.anime_id == Anime.id) \
        .join(AnimeGenre, AnimeGenre.anime_id == Anime.id) \
        .join(AnimeEpisodesPerSeason, AnimeEpisodesPerSeason.anime_id == Anime.id) \
        .filter(AnimeList.user_id == user_id).group_by(Anime.id).order_by(Anime.name.asc()).all()

    movies_data = db.session.query(Movies, MoviesList, func.group_concat(MoviesGenre.genre.distinct())) \
        .join(MoviesList, MoviesList.movies_id == Movies.id) \
        .join(MoviesGenre, MoviesGenre.movies_id == Movies.id) \
        .filter(MoviesList.user_id == user_id).group_by(Movies.id).order_by(Movies.name.asc()).all()

    total_data = series_data + anime_data + movies_data

    def get_episodes_and_time(element):
        if element[1].status == Status.COMPLETED or element[1].status == Status.COMPLETED_ANIMATION:
            try:
                return [1, element[0].runtime]
            except:
                return [element[0].total_episodes, int(element[0].episode_duration) * element[0].total_episodes]
        elif element[1].status != Status.PLAN_TO_WATCH and element[1].status != Status.RANDOM:
            nb_season = len(element[3].split(","))
            nb_episodes = element[4].split(",")[:nb_season]

            ep_duration = int(element[0].episode_duration)
            ep_counter = 0
            for i in range(0, element[1].current_season - 1):
                ep_counter += int(nb_episodes[i])
            episodes_watched = ep_counter + element[1].last_episode_watched
            time_watched = (ep_duration * episodes_watched)
            return [episodes_watched, time_watched]
        else:
            return [0, 0]

    time_by_genre = {}
    for element in total_data:
        eps_and_time = get_episodes_and_time(element)
        episodes_watched = eps_and_time[0]
        time_watched = eps_and_time[1]

        # Genres badges
        genres = element[2].split(',')
        for genre in genres:
            if genre not in time_by_genre:
                time_by_genre[genre] = time_watched/60
            else:
                time_by_genre[genre] += time_watched/60

    time_by_genre

    return time_by_genre


