#!/usr/bin/perl

use strict;
use warnings;
use DBI;
use Fcntl qw/:flock SEEK_END/;
require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d);
my %session;
my $authd = 0;
my $logd_in = 0;
my $id;
my $full_user = 0;
my @privs;
my @cm_classes;

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;
	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}
	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		$id = $session{"id"};
		#privileges set
		if (exists $session{"privileges"}) {
			my $priv_str = $session{"privileges"};
			my $spc = " ";
			$priv_str =~ s/\+/$spc/g;
			$priv_str =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			if ($priv_str eq "all") { 
				$full_user++;
				$authd++;
			}
			else {
				if (exists $session{"token_expiry"} and $session{"token_expiry"} =~ /^\d+$/) {
					if ($session{"token_expiry"} > time) {
						@privs = split/,/,$priv_str;
						my $cntr = 0;
						foreach (@privs) {
							if ($_ =~ /^CM\((.*)\)$/i) {	
								push @cm_classes, $1;
								$authd++;
							}
						}
					}
				}
			}
		}
	}
}


my %auth_params;
my $valid_data_posted = 0;
if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	$valid_data_posted = 1;
	my $str = "";

	while (<STDIN>) {
               	$str .= $_;
       	}

	my $space = " ";
	$str =~ s/\x2B/$space/ge;

	my @auth_req = split/&/,$str;
	for my $auth_req_line (@auth_req) {
		
		my $eqs = index($auth_req_line, "=");	
		if ($eqs > 0) {
			my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1)); 
			$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$auth_params{$k} = $v;
		}
	}
}

my $content = '';
my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Exam Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a>&nbsp;--&gt;&nbsp;<a href="/cgi-bin/createmarksheet.cgi">Create Marksheet</a>
	<hr> 
};

my $con;
my ($classes_seen, $subjects_seen) = (0,0);
if ($authd) {

	my $current_yr = (localtime)[5] + 1900;
	my @errors = ();
	my $feedback = '';

	my $study_years = 0;
	my ($class_err, $subject_err) = ("", "");
	my ($class, $subject);
	$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});	

	my @subjects = ();
	my @classes = ();
	my $exam = undef;

	
	if ($con) {
		my $prep_stmt3 = $con->prepare("SELECT id,value FROM vars WHERE id='1-subjects' OR id='1-classes' OR id='1-exam' LIMIT 3");
		if ($prep_stmt3) {
			my $rc = $prep_stmt3->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt3->fetchrow_array()) {
					if ($rslts[0] eq "1-subjects") {
						$subjects_seen++;
						if ($full_user) {
							@subjects = split/,/,$rslts[1];
						}
						else {
							my @all_subjs = split/,/,$rslts[1];
							for my $test_subj (@all_subjs) {
								TEST_1: for my $cm_class (@cm_classes) {
									if ($cm_class =~ /\s+$test_subj$/i) {
										push @subjects, $test_subj;
										last TEST_1; 
									}
								}
							}
						}
					}
					elsif ($rslts[0] eq "1-classes") {
						$classes_seen++;
						if ($full_user) {
							@classes = split/,/,$rslts[1];
						}
						else {
							my @all_classes = split/,/,$rslts[1];
							for my $test_class (@all_classes) {
								TEST_2: for my $cm_class (@cm_classes) {
									if ($cm_class =~ /^$test_class\s+/i) {
										push @classes, $test_class;
										last TEST_2; 
									}
								}
							}
						}
					}
					elsif ($rslts[0] eq "1-exam") {
						$exam = $rslts[1];
						if ($exam =~ /(\d{4,})/) {
							$current_yr = $1;
						}
						else {
							$exam .= "($current_yr)";
						}
					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM  vars statement: ", $prep_stmt3->errstr, $/;
			}
		}
		else {
			print STDERR "Could not prepare SELECT FROM vars statement: ", $prep_stmt3->errstr, $/;
		}
	}

	#process POSTed data
	
	VALID_DATA_POSTED: {
	if ($valid_data_posted) {
		my $fail = 0;
		my @errors;
		unless ( exists $auth_params{"confirm_code"} and exists $session{"confirm_code"} and ($auth_params{"confirm_code"} eq $session{"confirm_code"}) ) {
			push @errors, "Your request was not sent with the appropriate token tokens. Do not alter any of the hidden values in this HTML form. To refresh your tokens, reload this page.";
			$fail++; 
		}
		unless (exists $auth_params{"class"}) {
			push @errors, "You did not specify the class for which you would like to create this marksheet";
			$fail++; 
		}
		else {
			$class = $auth_params{"class"};
			CLASS: for (my $i = 0; $i <= @classes; $i++) {
				if ($i == @classes) {
					$fail++;
					push @errors, "The class you specified is not one of those recognized by the system. Make sure the 'classes' system variable is correctly set by the administrator.";
					$class_err = qq{<span style="color: red">*</span>};
				}
				elsif (lc($classes[$i]) eq lc($class)) {
					$class = $classes[$i];
					last CLASS;
				}
			}
		}

		unless (exists $auth_params{"subject"}) {
			push @errors, "You did not specify the subject for which you would like to create this marksheet";
			$fail++; 
		}
		else {
			$subject = $auth_params{"subject"};
			SUBJECT: for (my $i = 0; $i <= @subjects; $i++) {
				if ($i == @subjects) {
					$fail++;
					push @errors, "The subject you specified is not one of those recognized by the system. Make sure the 'subjects' system variable is correctly set by the administrator.";
					$subject_err = qq{<span style="color: red">*</span>};
				}
				elsif (lc($subjects[$i]) eq lc($subject)) {
					$subject = $subjects[$i];
					last SUBJECT;
				}
			}
		}

		if ($fail) {
			if (@errors == 1) {
				$feedback = qq{<span style="color: red">The following issue was detected with your request:</span>};
			}
			else {
				$feedback = qq{<span style="color: red">The following issues were detected with your request:</span>};
			}
			$feedback .= "<ul>";
			foreach (@errors) {
				$feedback .= "<li>" . $_;
			}
			$feedback .= "</ul>";
			$valid_data_posted = 0;
			last VALID_DATA_POSTED;
		}

		my %all_rolls;

		my $prep_stmt1 = $con->prepare("SELECT table_name,class,start_year FROM student_rolls");
		my $solved = 0;
		my $assoc_roll = undef;
 
		if ($prep_stmt1) {	
			my $rc = $prep_stmt1->execute();
			if ($rc) {
				while (my @rslts = $prep_stmt1->fetchrow_array()) {
					#pass over the remaining rows to unvoid unfinished errors
					next if ($solved);
					my ($table_name,$saved_class,$start_year) = @rslts;
					my $class_yr = ($current_yr - $start_year) + 1;
					$saved_class =~ s/\d+/$class_yr/;
					#print "X-Debug-$rslts[0]: do cmp btn $saved_class & $class\r\n";
					if (lc($class) eq lc($saved_class)) {
						$solved++;
						$assoc_roll = $table_name;
					}
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt1->errstr, $/;
			}
		}
		else {
			print STDERR "Could not create SELECT FROM student_rolls statement: ", $prep_stmt1->errstr, $/; 
		}
		#this student roll has not been created yet
		unless (defined $assoc_roll) {
			$feedback = "<span style='color: red'>The data for <em>$class</em> has not been loaded into the system yet. To continue, please create this student roll.</span>";
			$valid_data_posted = 0;
			last VALID_DATA_POSTED;
		}

		my $collision = undef;
		my $prep_stmt2 = $con->prepare("SELECT table_name FROM marksheets WHERE roll=? AND exam_name=? AND subject=? LIMIT 1");
		if ($prep_stmt2) {	
			my $rc = $prep_stmt2->execute($assoc_roll,$exam,$subject);
			if ($rc) {
				my @rslts = $prep_stmt2->fetchrow_array();
				if (@rslts) {	
					$collision = $rslts[0];
				}
			}
			else {
				print STDERR "Could not execute SELECT FROM student_rolls statement: ", $prep_stmt2->errstr, $/;
			}
		}
		else {
			print STDERR "Could not create SELECT FROM student_rolls statement: ", $prep_stmt2->errstr, $/; 
		}

		if (defined $collision) {
			$content =
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Create Student Roll</title>
</head>
<body>
$header
The marksheet for <em>$class $exam $subject</em> already exists. Would you like to <a href="/cgi-bin/editmarksheet.cgi?marksheet=$collision">use this marksheet?</a>
</body>
</html>
};
			last VALID_DATA_POSTED;
		}

		else {
			#generate 4 possible names for the table to be created
			#fallback plan(incase there's a collision with all 5 names) is the current time
			#not much of a fallback plan, though. But the odds of a 5-way collision are slim
			my %possib_table_names = ();
			foreach (0..4) {
				$possib_table_names{gen_token(1)}++;
			}
			
			my @where_clause_bits = ();
			foreach (keys %possib_table_names) {
				push @where_clause_bits, "table_name=?";
			}
			
			my $where_clause = 'WHERE ' . join(' OR ', @where_clause_bits);

			my $prep_stmt4 = $con->prepare("SELECT table_name FROM marksheets $where_clause");
				if ($prep_stmt4) {
					my $rc = $prep_stmt4->execute(keys %possib_table_names);
					if ($rc) {
						while (my @rslts = $prep_stmt4->fetchrow_array()) {
							delete $possib_table_names{$rslts[0]};	
						}
					}
					else {
						print STDERR "Could not execute SELECT FROM marksheets: ", $prep_stmt4->errstr, $/;
					}
				}
				else {
					print STDERR "Could not prepare SELECT FROM marksheets: ", $prep_stmt4->errstr, $/;
				}
			my $t_name = time;
			if ( keys(%possib_table_names) ) {
				$t_name = (keys %possib_table_names)[0];
			}
			#add record to DB
			my $prep_stmt5 = $con->prepare("INSERT INTO marksheets VALUES(?,?,?,?,?)");
			if ($prep_stmt5) {
				my $rc = $prep_stmt5->execute($t_name,$assoc_roll,$exam,$subject,time);
				if ($rc) {
					#update privileges
					unless ($full_user) {
						my $prep_stmt6 = $con->prepare(qq{UPDATE tokens SET privileges=concat(privileges, ',EM($class $subject)') WHERE value=? LIMIT 1});
						if ($prep_stmt6) {
							my $rc = $prep_stmt6->execute($id);	
							unless ($rc) {
								print STDERR "Could not UPDATE tokens: ", $prep_stmt6->errstr, $/;	
							}
						}
						push @privs, "EM($class $subject)";
						$session{"privileges"} = join(',', @privs);
					}
					#create table
					my $prep_stmt7 = $con->prepare("CREATE TABLE `$t_name` (adm smallint unsigned unique, marks smallint unsigned)");
					if ($prep_stmt7) {
						my $rc = $prep_stmt7->execute();
						unless ($rc) {
							print STDERR "Could not CREATE TABLE: ", $prep_stmt7->errstr, $/;	
						}
					}
					#log action
					my @today = localtime;	
					my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];
					open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
        				if ($log_f) {
                				@today = localtime;	
						my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
						flock ($log_f, LOCK_EX) or print STDERR "Could not log create student roll for $id due to flock error: $!$/";
						seek ($log_f, 0, SEEK_END);
		 				print $log_f "$id CREATE MARKSHEET ($class $exam $subject) $time\n";
						flock ($log_f, LOCK_UN);
                				close $log_f;
        				}
					else {
						print STDERR "Could not log create student roll for $id: $!\n";
					}
					$content =
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Create Marksheet</title>
</head>
<body>
$header
The marksheet for <em>$class $exam $subject</em> has been created! Would you like to <a href="/cgi-bin/editmarksheet.cgi?marksheet=$t_name">use this marksheet</a>
</body>
</html>
};
				}
				else {
					print STDERR "Could not execute INSERT INTO marksheets statement: ", $prep_stmt5->errstr, $/;
				}
			}
			else {
				print STDERR "Could not create INSERT INTO marksheets statement: ", $prep_stmt5->errstr, $/;
			}
			$con->commit();
		}
	}
	}
	#display create marksheet FORM 
	#used another 'if' instead of an 'else' because
	#if an error is spotted with the data POSTed
	#the user is presented with a form afresh
	if (not $valid_data_posted) {

			$content =
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Create Student Roll</title>
</head>
<body>
$header
$feedback};
		if (defined $exam) {
			if (@classes) {	
				if (@subjects) {
					my $classes_menu = qq{<SELECT name="class">};
					foreach (@classes) {
						$classes_menu .= qq{<OPTION value="$_">$_</OPTION>};
					}
					$classes_menu .= qq{</SELECT>};
				
					my $subjects_menu = qq{<SELECT name="subject">};
					foreach (@subjects) {
						$subjects_menu .= qq{<OPTION value="$_">$_</OPTION>};
					}
					$subjects_menu .= qq{</SELECT>};
 					my $conf_code = gen_token();
					$session{"confirm_code"} = $conf_code;	 
					$content .=
qq{<FORM method="POST" action="/cgi-bin/createmarksheet.cgi">
<input type="hidden" name="confirm_code" value="$conf_code"> 
<table cellpadding="2%">
<tr><td><label for="exam">Exam</label><td><input type="text" disabled value="$exam" name="exam" size="30">
<tr><td>$class_err<label for="class">Class</label><td>$classes_menu
<tr><td>$subject_err<label for="subject">Subject</label><td>$subjects_menu
<tr><td><input type="submit" name="create_marksheet" value="Create">
</table>
</form>
};
				}
				else {
					if ($subjects_seen) {
						$content .= "<em>None of the subjects you have been authorized to create marksheets for exist in the system. This could either be due to a misconfiguration of the 'subjects' system variable or your token.</em>";
					}
					else {
						$content .= "<em>To proceed, ask the adminisrator to set the 'subjects' system variable through the Administrator Panel</em>";
					}
				}
			}
			else {
				if ($classes_seen) {
					$content .= "<em>None of the classes you have been authorized to create marksheets for exist in the system. This could either be due to a misconfiguration of the 'classes' system variable or your token.</em>";
				}
				else {
					$content .= "<em>To proceed, ask the adminisrator to set the 'classes' system variable through the Administrator Panel</em>";
				}
			}
		}
		else {
			$content .= "<em>To proceed, ask the administrator to set the 'exam' system variable through the Administrator Panel.</em>"
		}
	}
	$content .= "</body></html>";
}
else {
	if ($logd_in) {
		$content = 
qq{
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj :: Exam Management Information System :: Create Marksheet</title>
</head>
<body>
$header
<em>Sorry. You are not authorized to create a marksheet.<br><br>Get an up-to-date token with the appropriate privileges from the administrator.</em>
</body>
</html>	
};
	}
	#user not logged in, send them to
	#the login page
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/createmarksheet.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
               	"<html>
               	<head>
		<title>Spanj: Exam Management Information System - Redirect Failed</title>
		</head>
         	<body>
                You should have been redirected to <a href=\"/login.html?cont=/cgi-bin/createmarksheet.cgi\">/login.html?cont=/cgi-bin/createmarksheet.cgi</a>. If you were not, <a href=\"/cgi-bin/createmarksheet.cgi\">Click Here</a> 
		</body>
                </html>";

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

