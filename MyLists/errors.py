from flask import render_template, url_for
from MyLists import app


@app.errorhandler(403)
def error403(e):
    image_error = url_for('static', filename='img/error.jpg')
    return render_template('error.html', error_code=403, title='Error', image_error=image_error), 403


@app.errorhandler(404)
def error404(e):
    image_error = url_for('static', filename='img/error.jpg')
    return render_template('error.html', error_code=404, title='Error', image_error=image_error), 404


@app.errorhandler(410)
def error410(e):
    image_error = url_for('static', filename='img/error.jpg')
    return render_template('error.html', error_code=410, title='Error', image_error=image_error), 410


@app.errorhandler(413)
def error413(e):
    image_error = url_for('static', filename='img/error.jpg')
    return render_template('error.html', error_code=413, title='Error', image_error=image_error), 413


@app.errorhandler(500)
def error500(e):
    image_error = url_for('static', filename='img/error.jpg')
    return render_template('error.html', error_code=500, title='Error', image_error=image_error), 500
